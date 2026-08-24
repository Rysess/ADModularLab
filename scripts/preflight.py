#!/usr/bin/env python3
"""Validate a lab definition against the roles and modules it references.

Run by ./run.sh before Terraform touches anything. Everything checked here is
something Terraform or Ansible would otherwise only discover 20 minutes into a
deployment.
"""
import ipaddress
import os
import re
import sys

import yaml

MEM = {
    "t3.nano": 0.5, "t3.micro": 1, "t3.small": 2, "t3.medium": 4,
    "t3.large": 8, "t3.xlarge": 16, "t3.2xlarge": 32,
    "t3a.nano": 0.5, "t3a.micro": 1, "t3a.small": 2, "t3a.medium": 4,
    "t3a.large": 8, "t3a.xlarge": 16, "t3a.2xlarge": 32,
    "t2.nano": 0.5, "t2.micro": 1, "t2.small": 2, "t2.medium": 4,
    "t2.large": 8, "t2.xlarge": 16,
    "m5.large": 8, "m5.xlarge": 16, "m5.2xlarge": 32,
    "m6i.large": 8, "m6i.xlarge": 16, "m6i.2xlarge": 32,
    "m6a.large": 8, "m6a.xlarge": 16, "m6a.2xlarge": 32,
    "c5.large": 4, "c5.xlarge": 8, "c6i.large": 4, "c6i.xlarge": 8,
    "r5.large": 16, "r6i.large": 16,
}
ROLE_DIR = {"dc": "dc", "member": "domain_member",
            "child_dc": "domain_child", "standalone": None}
VALID_OS = {"windows", "linux"}
VALID_PROTO = {"tcp", "udp"}
VALID_EXPIRES_ACTION = {"stop", "terminate"}
WINDOWS_VERSIONS = {"2016", "2019", "2022", "2025"}

SUBNET = ipaddress.ip_network("10.0.1.0/24")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,14}$")
LAB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
                       r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
AMI_RE = re.compile(r"^ami-[0-9a-f]{8,17}$")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ROLE_DIRS = [os.path.join(ROOT, "ansible", "roles"),
             os.path.join(ROOT, "ansible", "modules")]


def meta(name):
    """Load a role or module's lab_meta.yml, or {} if it declares none."""
    for d in ROLE_DIRS:
        p = os.path.join(d, name, "lab_meta.yml")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    return {}


def known(name):
    return any(os.path.isdir(os.path.join(d, name)) for d in ROLE_DIRS)


def module_names(host, problems):
    """A modules entry is either a bare name or {name: <n>, vars: {...}}."""
    names = []
    for entry in host.get("modules") or []:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            extra = set(entry) - {"name", "vars"}
            if extra:
                problems.append(f"{host.get('name')}: module {entry['name']!r} has "
                                f"unknown keys {sorted(extra)}; expected 'name' and 'vars'")
            if "vars" in entry and not isinstance(entry["vars"], dict):
                problems.append(f"{host.get('name')}: module {entry['name']!r} "
                                f"'vars' must be a mapping")
            names.append(entry["name"])
        else:
            problems.append(f"{host.get('name')}: module entry {entry!r} must be a name "
                            f"or a mapping with a 'name' key")
    return names


def check_lab(lab, problems):
    name = lab.get("name", "")
    if not LAB_NAME_RE.match(str(name)):
        problems.append(f"lab.name {name!r}: 1-64 chars, alphanumeric plus '.', '_' and '-' "
                        f"(it becomes the EC2 tag the inventory filters on)")
    if not REGION_RE.match(str(lab.get("region", ""))):
        problems.append(f"lab.region {lab.get('region')!r} is not an AWS region id")

    admin = str(lab.get("domain_admin", ""))
    if not admin:
        problems.append("lab.domain_admin is required")
    elif len(admin) > 20:
        problems.append(f"lab.domain_admin {admin!r} exceeds the 20-character "
                        f"sAMAccountName limit")

    hours = lab.get("expires_hours", 168)
    if not isinstance(hours, int) or hours <= 0:
        problems.append(f"lab.expires_hours {hours!r} must be a positive integer")

    action = lab.get("expires_action", "stop")
    if action not in VALID_EXPIRES_ACTION:
        problems.append(f"lab.expires_action {action!r} must be one of "
                        f"{sorted(VALID_EXPIRES_ACTION)}")

    enabled = lab.get("expires_enabled", True)
    if not isinstance(enabled, bool):
        problems.append(f"lab.expires_enabled {enabled!r} must be true or false")


def check_defaults(defaults, problems):
    win = str(defaults.get("windows_version", "2022"))
    if win not in WINDOWS_VERSIONS:
        problems.append(f"defaults.windows_version {win!r} must be one of "
                        f"{sorted(WINDOWS_VERSIONS)}")
    ubuntu = str(defaults.get("ubuntu_release", "22.04"))
    if not re.match(r"^\d{2}\.\d{2}$", ubuntu):
        problems.append(f"defaults.ubuntu_release {ubuntu!r} must look like 22.04")


def check_expose_ports(host, problems):
    name = host.get("name")
    for entry in host.get("expose_ports") or []:
        if not isinstance(entry, dict):
            problems.append(f"{name}: expose_ports entry {entry!r} must be a mapping "
                            f"with 'port' and 'proto'")
            continue
        port = entry.get("port")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            problems.append(f"{name}: expose_ports port {port!r} must be 1-65535")
        proto = entry.get("proto")
        if proto not in VALID_PROTO:
            problems.append(f"{name}: expose_ports proto {proto!r} must be one of "
                            f"{sorted(VALID_PROTO)}")


def check_private_ip(host, seen_ips, problems):
    name = host.get("name")
    ip = host.get("private_ip")
    if not ip:
        return
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        problems.append(f"{name}: private_ip {ip!r} is not a valid address")
        return
    if addr not in SUBNET:
        problems.append(f"{name}: private_ip {ip} is outside {SUBNET}")
    elif int(addr) - int(SUBNET.network_address) < 4 or addr == SUBNET.broadcast_address:
        problems.append(f"{name}: private_ip {ip} is reserved by AWS")
    if ip in seen_ips:
        problems.append(f"{name}: private_ip {ip} already used by {seen_ips[ip]}")
    seen_ips[ip] = name


def parent_domain(domain):
    """A child domain's parent is that domain minus its first label."""
    return domain.split(".", 1)[1] if "." in domain else ""


def check_domains(hosts, problems):
    """Every domain a host belongs to must be served by a controller."""
    roots = {h["domain"] for h in hosts
             if h.get("role") == "dc" and h.get("domain")}
    children = {h["domain"] for h in hosts
                if h.get("role") == "child_dc" and h.get("domain")}

    for h in hosts:
        name, role, domain = h.get("name"), h.get("role", "standalone"), h.get("domain")

        if role in ("dc", "child_dc", "member") and not domain:
            problems.append(f"{name}: role={role} must declare 'domain'")
            continue
        if not domain:
            continue

        if role == "child_dc":
            parent = parent_domain(domain)
            if not parent:
                problems.append(f"{name}: child domain {domain!r} needs a parent, "
                                f"as in child.lab.local")
            elif parent not in roots:
                problems.append(f"{name}: parent {parent!r} is not served by any "
                                f"role=dc host. Known: {sorted(roots) or 'none'}")
            if domain in roots:
                problems.append(f"{name}: {domain!r} is already a forest root")
        elif role == "member" and domain not in roots | children:
            problems.append(f"{name}: joins {domain!r}, which no controller serves. "
                            f"Known: {sorted(roots | children) or 'none'}")

    seen = {}
    for h in hosts:
        if h.get("role") in ("dc", "child_dc") and h.get("domain"):
            if h["domain"] in seen:
                problems.append(f"{h['name']}: {h['domain']!r} is already served by "
                                f"{seen[h['domain']]}")
            seen[h["domain"]] = h["name"]


def check_requirements(host, role, roles, itype, lab_roles, lab_modules, problems, warns):
    """Check each applied role/module against its lab_meta.yml declaration."""
    name = host.get("name")
    host_os = host.get("os")

    for r in roles:
        m = meta(r)

        req_os = m.get("os", "any")
        if req_os != "any" and req_os != host_os:
            problems.append(f"{name}: role '{r}' requires os={req_os}, host is {host_os}")

        req_role = m.get("requires_role")
        if req_role and role != req_role:
            problems.append(f"{name}: '{r}' must run on a host with role={req_role}, "
                            f"host is {role}")

        req_lab_role = m.get("requires_lab_role")
        if req_lab_role and req_lab_role not in lab_roles:
            problems.append(f"{name}: '{r}' needs a host with role={req_lab_role} in the lab")

        for dep in m.get("requires_lab", []):
            if dep not in lab_modules:
                problems.append(f"{name}: '{r}' needs module '{dep}' somewhere in the lab")

        mint = m.get("min_instance_type")
        if mint:
            hr, mr = MEM.get(itype), MEM.get(mint)
            if hr is None:
                warns.append(f"{name}: unknown instance_type '{itype}', "
                             f"cannot verify '{r}' needs >= {mint}")
            elif mr is not None and hr < mr:
                problems.append(f"{name}: role '{r}' needs >= {mint}, host is {itype}")


def main():
    lab_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "lab.yml")
    with open(lab_file, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    lab = cfg.get("lab") or {}
    defaults = cfg.get("defaults") or {}
    hosts = cfg.get("hosts") or []
    problems, warns = [], []

    if not hosts:
        print("Preflight FAILED:\n  - no hosts declared")
        sys.exit(1)

    check_lab(lab, problems)
    check_defaults(defaults, problems)
    check_domains(hosts, problems)

    seen_names, seen_ips = set(), {}
    lab_roles = {h.get("role", "standalone") for h in hosts}
    host_modules = {}
    for h in hosts:
        host_modules[id(h)] = module_names(h, problems)
    lab_modules = {m for mods in host_modules.values() for m in mods}

    for h in hosts:
        name = h.get("name", "")
        if not NAME_RE.match(str(name)):
            problems.append(f"{name!r}: invalid host name (1-15 chars, alphanumeric and '-')")
        if name in seen_names:
            problems.append(f"{name}: duplicate host name")
        seen_names.add(name)

        host_os = h.get("os")
        if host_os not in VALID_OS:
            problems.append(f"{name}: os must be one of {sorted(VALID_OS)}, got {host_os!r}")
            continue

        role = h.get("role", "standalone")
        if role not in ROLE_DIR:
            problems.append(f"{name}: unknown role {role!r}")

        win = h.get("windows_version")
        if win is not None:
            if host_os != "windows":
                problems.append(f"{name}: windows_version is only valid on a windows host")
            elif str(win) not in WINDOWS_VERSIONS:
                problems.append(f"{name}: windows_version {win!r} must be one of "
                                f"{sorted(WINDOWS_VERSIONS)}")

        ami = h.get("ami")
        if ami is not None and not AMI_RE.match(str(ami)):
            problems.append(f"{name}: ami {ami!r} is not an AMI id (ami-...)")

        host_vars = h.get("vars")
        if host_vars is not None and not isinstance(host_vars, dict):
            problems.append(f"{name}: 'vars' must be a mapping")
        elif host_vars and "domain_name" in host_vars:
            problems.append(f"{name}: set the host's 'domain' field rather than "
                            f"vars.domain_name")

        dom = h.get("domain")
        if dom is not None:
            if not DOMAIN_RE.match(str(dom)):
                problems.append(f"{name}: domain {dom!r} must be a dotted DNS name")
            elif len(str(dom).split(".")[0]) > 15:
                problems.append(f"{name}: domain {dom!r}: the first label becomes the "
                                f"NetBIOS name and must be 15 characters or fewer")

        disk = h.get("disk_gb")
        if disk is not None and (not isinstance(disk, int) or disk < 8):
            problems.append(f"{name}: disk_gb {disk!r} must be an integer of at least 8")

        check_private_ip(h, seen_ips, problems)
        check_expose_ports(h, problems)

        mods = host_modules[id(h)]
        dupes = {m for m in mods if mods.count(m) > 1}
        if dupes:
            problems.append(f"{name}: module(s) {sorted(dupes)} listed more than once")

        # EC2 drops forwarded traffic unless the source/dest check is off.
        if "vpn" in mods and h.get("source_dest_check", True):
            problems.append(f"{name}: runs the vpn module, so it needs "
                            f"source_dest_check: false")

        itype = h.get("instance_type") or defaults.get(f"{host_os}_instance_type")
        roles = []
        rd = ROLE_DIR.get(role)
        if rd:
            roles.append(rd)
        for m in mods:
            if not known(m):
                problems.append(f"{name}: unknown module {m!r}")
            else:
                roles.append(m)

        check_requirements(h, role, roles, itype, lab_roles, lab_modules, problems, warns)

    for w in warns:
        print(f"[warn] {w}")
    if problems:
        print("\nPreflight FAILED:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix the lab file, or bypass with:  ./run.sh --force   (or SKIP_PREFLIGHT=1)")
        sys.exit(1)
    print("[preflight] OK - every host satisfies its roles' requirements")


if __name__ == "__main__":
    main()
