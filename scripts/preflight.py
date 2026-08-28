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
VPN_CLIENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VALID_ACL_RIGHTS = {"GenericAll", "GenericWrite", "WriteDacl", "WriteOwner",
                    "WriteProperty", "ReadProperty", "Self", "ExtendedRight"}
VALID_ACL_ACCESS = {"Allow", "Deny"}
VALID_EXPIRES_ACTION = {"stop", "terminate"}
WINDOWS_VERSIONS = {"2016", "2019", "2022", "2025"}
WINDOWS_EDITIONS = {"full", "core"}
GROUP_SCOPES = {"global", "domainlocal", "universal"}
GROUP_CATEGORIES = {"security", "distribution"}
IDENTITY_USER_KEYS = {"display", "description", "firstname", "surname",
                      "email", "password", "enabled", "ou"}
IDENTITY_GROUP_KEYS = {"description", "scope", "category", "members", "ou"}
LOGON_LISTS = ("logon_admins", "logon_rdp", "logon_interactive", "logon_batch",
               "logon_deny_interactive", "logon_deny_rdp", "logon_deny_network")

# Adding members to these via identity_groups would try to re-cast their scope.
DOMAINLOCAL_BUILTINS = {
    "administrators", "users", "guests", "remote desktop users",
    "backup operators", "server operators", "account operators",
    "print operators", "remote management users", "cert publishers",
}

# Denying these network logon locks Ansible (WinRM, as local Administrator) out.
LOCKOUT_PRINCIPALS = {
    "administrator", "administrators", ".\\administrator", ".\\administrators",
    "builtin\\administrators",
}

# A group may only contain members of these scopes.
GROUP_NESTING = {
    "global": {"global"},
    "universal": {"global", "universal"},
    "domainlocal": {"global", "universal", "domainlocal"},
}

WELL_KNOWN = {n.lower() for n in (
    "Administrator", "Guest", "krbtgt",
    "Domain Admins", "Domain Users", "Domain Computers", "Domain Guests",
    "Domain Controllers", "Enterprise Admins", "Schema Admins",
    "Group Policy Creator Owners", "Cert Publishers", "DnsAdmins",
    "Protected Users", "Read-only Domain Controllers",
    "Administrators", "Users", "Guests", "Backup Operators",
    "Remote Desktop Users", "Server Operators", "Account Operators",
    "Print Operators", "Power Users", "Remote Management Users",
    "Everyone", "Authenticated Users", "SYSTEM", "NETWORK SERVICE",
    "LOCAL SERVICE", "INTERACTIVE", "NETWORK", "BATCH", "SERVICE",
)}

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


def defaults_of(name):
    """A module's defaults/main.yml, or {} if it has none."""
    for d in ROLE_DIRS:
        p = os.path.join(d, name, "defaults", "main.yml")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fh:
                return yaml.safe_load(fh) or {}
    return {}


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


def _str_list(where, key, value, problems):
    """Validate a list-of-non-empty-strings module var and return it."""
    if not isinstance(value, list):
        problems.append(f"{where}: {key} must be a list")
        return []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            problems.append(f"{where}: {key} entry {entry!r} must be a non-empty string")
    return [e for e in value if isinstance(e, str)]


def check_identity_vars(where, mv, problems, warns):
    ous = set(_str_list(where, "identity_ous", mv.get("identity_ous", []), problems))
    for ou in sorted(ous):
        parent = ou.rsplit("/", 1)[0]
        if "/" in ou and parent not in ous:
            problems.append(f"{where}: identity_ous {ou!r} nests under {parent!r}, "
                            f"which is not listed")

    scopes = {}
    for key, allowed, member_key in (("identity_groups", IDENTITY_GROUP_KEYS, "members"),
                                     ("identity_users", IDENTITY_USER_KEYS, None)):
        entries = mv.get(key, {})
        if not isinstance(entries, dict):
            problems.append(f"{where}: {key} must be a mapping of name to definition")
            continue
        for who, spec in entries.items():
            if not isinstance(who, str) or not who.strip():
                problems.append(f"{where}: {key} has a non-string name {who!r}")
                continue
            if len(who) > 20:
                problems.append(f"{where}: {key} {who!r} exceeds the 20-character "
                                f"sAMAccountName limit")
            if isinstance(spec, dict):
                extra = set(spec) - allowed
                if extra:
                    problems.append(f"{where}: {key} {who!r} has unknown keys "
                                    f"{sorted(extra)}; expected {sorted(allowed)}")
                if member_key and member_key in spec:
                    _str_list(f"{where}: {key} {who!r}", member_key, spec[member_key], problems)
            elif key == "identity_groups" and not isinstance(spec, list):
                problems.append(f"{where}: identity_groups {who!r} must be a member "
                                f"list or a mapping")
            elif key == "identity_users" and not isinstance(spec, str):
                problems.append(f"{where}: identity_users {who!r} must be a display "
                                f"name or a mapping")
            if key == "identity_groups":
                scope = spec.get("scope", "global") if isinstance(spec, dict) else "global"
                scopes[who.lower()] = scope

    for who, spec in (mv.get("identity_groups") or {}).items():
        if not isinstance(spec, dict):
            continue
        scope = spec.get("scope")
        if scope is not None and scope not in GROUP_SCOPES:
            problems.append(f"{where}: identity_groups {who!r} scope {scope!r} must be "
                            f"one of {sorted(GROUP_SCOPES)}")
        cat = spec.get("category")
        if cat is not None and cat not in GROUP_CATEGORIES:
            problems.append(f"{where}: identity_groups {who!r} category {cat!r} must be "
                            f"one of {sorted(GROUP_CATEGORIES)}")

    for who in (mv.get("identity_groups") or {}):
        if str(who).lower() in DOMAINLOCAL_BUILTINS:
            warns.append(f"{where}: identity_groups {who!r} is a built-in domain-local "
                         f"group; adding members here tries to change its scope. Add the "
                         f"member through the user's 'groups' instead")

    for who, spec in (mv.get("identity_groups") or {}).items():
        members = spec.get("members", []) if isinstance(spec, dict) else spec
        if not isinstance(members, list):
            continue
        outer = scopes.get(str(who).lower(), "global")
        allowed = GROUP_NESTING.get(outer, set())
        for member in members:
            inner = scopes.get(str(member).lower())
            if inner is not None and inner not in allowed:
                problems.append(f"{where}: identity_groups {who!r} is {outer} and "
                                f"cannot contain the {inner} group {member!r}")

    # Two users sharing a display name in one container collide on the CN.
    seen_cn = {}
    for who, spec in (mv.get("identity_users") or {}).items():
        if isinstance(spec, dict):
            display = spec.get("display") or who
            ou = spec.get("ou") or ""
        elif isinstance(spec, str):
            display, ou = (spec or who), ""
        else:
            continue
        cn = (str(display).lower(), str(ou).lower())
        if cn in seen_cn:
            problems.append(f"{where}: identity_users {who!r} and {seen_cn[cn]!r} share "
                            f"the display name {display!r} in the same container; give "
                            f"one a different display or 'ou'")
        seen_cn[cn] = who

    # A member is resolved by sAMAccountName (a key/LabUser/built-in), not a display name.
    defined = ({u.lower() for u in (mv.get("identity_users") or {})}
               | {g.lower() for g in (mv.get("identity_groups") or {})}
               | WELL_KNOWN)
    refs = []
    for who, spec in (mv.get("identity_groups") or {}).items():
        members = spec.get("members", []) if isinstance(spec, dict) else spec
        refs += [(f"identity_groups {who!r} member", m) for m in members
                 if isinstance(m, str)]
    for label, ref in refs:
        if ref.lower() in defined or re.match(r"^LabUser\d+$", ref):
            continue
        warns.append(f"{where}: {label} {ref!r} matches no user or group defined here; "
                     f"members are resolved by sAMAccountName (the map key), not display "
                     f"name")


def declared_principals(hosts):
    """Names this lab file creates, for spotting a logon list that misspells one."""
    names = set(WELL_KNOWN)
    default_groups = {g.lower() for g in defaults_of("identity")
                      .get("identity_groups", {})}
    for h in hosts:
        names.add(str(h.get("name", "")).lower())
        mvars = module_vars(h)
        for mod in module_names(h, []):
            names |= {p.lower() for p in meta(mod).get("provides_principals", [])}
            if mod != "identity":
                continue
            mv = mvars.get("identity", {})
            for key in ("identity_users", "identity_groups"):
                names |= {w.lower() for w in (mv.get(key) or {}) if isinstance(w, str)}
            # No explicit groups means the module's default org chart applies.
            if "identity_groups" not in mv:
                names |= default_groups
    return names


def check_logon_vars(host, where, mv, lab_modules, declared, problems, warns):
    for key in LOGON_LISTS:
        if key in mv:
            _str_list(where, key, mv[key], problems)
    keep = mv.get("logon_keep_administrators", True)
    if not isinstance(keep, bool):
        problems.append(f"{where}: logon_keep_administrators must be true or false")

    # logon_keep_administrators only protects allow lists, never deny lists.
    for p in mv.get("logon_deny_network") or []:
        if isinstance(p, str) and p.lower() in LOCKOUT_PRINCIPALS:
            problems.append(f"{where}: logon_deny_network includes {p!r}, which denies "
                            f"the local Administrator its WinRM logon and leaves the host "
                            f"unreachable; deny a specific domain group instead")

    for key in LOGON_LISTS:
        for p in mv.get(key) or []:
            if not isinstance(p, str) or "\\" in p or "@" in p:
                continue
            if p.rstrip("$").lower() in declared or re.match(r"^LabUser\d+$", p):
                continue
            warns.append(f"{where}: {key} names {p!r}, which this lab file does not "
                         f"create; it must already exist or the run will fail on it")

    rdp_open = any(e.get("port") == 3389 for e in host.get("expose_ports") or []
                   if isinstance(e, dict))
    if mv.get("logon_rdp") and not rdp_open and "vpn" not in lab_modules:
        warns.append(f"{host.get('name')}: grants RDP but 3389 is neither exposed "
                     f"nor reachable over a vpn module")


def check_vpn_vars(where, mv, problems):
    clients = mv.get("vpn_clients")
    if clients is None:
        return
    if not isinstance(clients, list) or not clients:
        problems.append(f"{where}: vpn_clients must be a non-empty list of names")
        return
    seen = set()
    for c in clients:
        if not isinstance(c, str) or not VPN_CLIENT_RE.match(c):
            problems.append(f"{where}: vpn_clients entry {c!r} must be 1-64 chars, "
                            f"alphanumeric plus '.', '_' and '-' (it is a cert name "
                            f"and a filename)")
        elif c.lower() in seen:
            problems.append(f"{where}: vpn_clients lists {c!r} twice")
        else:
            seen.add(c.lower())


def check_acl_vars(where, mv, declared, problems, warns):
    grants = mv.get("acl_grants")
    if grants is None:
        return
    if not isinstance(grants, list):
        problems.append(f"{where}: acl_grants must be a list")
        return
    for g in grants:
        if not isinstance(g, dict):
            problems.append(f"{where}: acl_grants entry {g!r} must be a mapping")
            continue
        for key in ("principal", "target", "right"):
            if not isinstance(g.get(key), str) or not g[key].strip():
                problems.append(f"{where}: acl_grants entry {g!r} needs a non-empty {key!r}")
        if isinstance(g.get("right"), str) and g["right"] not in VALID_ACL_RIGHTS:
            problems.append(f"{where}: acl_grants right {g['right']!r} must be one of "
                            f"{sorted(VALID_ACL_RIGHTS)}")
        access = g.get("access", "Allow")
        if access not in VALID_ACL_ACCESS:
            problems.append(f"{where}: acl_grants access {access!r} must be Allow or Deny")
        for key in ("principal", "target"):
            ref = g.get(key)
            if isinstance(ref, str) and ref.strip():
                bare = ref.rstrip("$")
                if bare.lower() not in declared and not re.match(r"^LabUser\d+$", bare):
                    warns.append(f"{where}: acl_grants {key} {ref!r} matches no principal "
                                 f"this lab creates; it must already exist")


def check_module_vars(host, mod, mv, lab_modules, declared, problems, warns):
    where = f"{host.get('name')}: module {mod!r}"
    if mod == "identity":
        check_identity_vars(where, mv, problems, warns)
    elif mod == "logon":
        check_logon_vars(host, where, mv, lab_modules, declared, problems, warns)
    elif mod == "vpn":
        check_vpn_vars(where, mv, problems)
    elif mod == "acl":
        check_acl_vars(where, mv, declared, problems, warns)


def module_vars(host):
    """{module name: its vars} for the entries that carry any."""
    out = {}
    for entry in host.get("modules") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) \
                and isinstance(entry.get("vars"), dict):
            out[entry["name"]] = entry["vars"]
    return out


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

    action = lab.get("expires_action", "terminate")
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
    ed = str(defaults.get("windows_edition", "full"))
    if ed not in WINDOWS_EDITIONS:
        problems.append(f"defaults.windows_edition {ed!r} must be one of "
                        f"{sorted(WINDOWS_EDITIONS)}")
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


def host_edition(host, defaults):
    return str(host.get("windows_edition", defaults.get("windows_edition", "full")))


def check_requirements(host, role, roles, itype, lab_roles, lab_modules, problems, warns,
                       edition="full"):
    """Check each applied role/module against its lab_meta.yml declaration."""
    name = host.get("name")
    host_os = host.get("os")

    for r in roles:
        m = meta(r)

        req_os = m.get("os", "any")
        if req_os != "any" and req_os != host_os:
            problems.append(f"{name}: role '{r}' requires os={req_os}, host is {host_os}")

        req_role = m.get("requires_role")
        if req_role:
            allowed = req_role if isinstance(req_role, list) else [req_role]
            if role not in allowed:
                problems.append(f"{name}: '{r}' must run on a host with "
                                f"role={'|'.join(allowed)}, host is {role}")

        req_lab_role = m.get("requires_lab_role")
        if req_lab_role and req_lab_role not in lab_roles:
            problems.append(f"{name}: '{r}' needs a host with role={req_lab_role} in the lab")

        for dep in m.get("requires_lab", []):
            if dep not in lab_modules:
                problems.append(f"{name}: '{r}' needs module '{dep}' somewhere in the lab")

        # Core needs less memory, so a role may declare a lower floor for it.
        mint = m.get("min_instance_type")
        if edition == "core":
            mint = m.get("min_instance_type_core", mint)
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
    declared = declared_principals(hosts)

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

        ed = h.get("windows_edition")
        if ed is not None:
            if host_os != "windows":
                problems.append(f"{name}: windows_edition is only valid on a windows host")
            elif str(ed) not in WINDOWS_EDITIONS:
                problems.append(f"{name}: windows_edition {ed!r} must be one of "
                                f"{sorted(WINDOWS_EDITIONS)}")

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

        for mod, mv in module_vars(h).items():
            check_module_vars(h, mod, mv, lab_modules, declared, problems, warns)

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

        check_requirements(h, role, roles, itype, lab_roles, lab_modules, problems, warns,
                           host_edition(h, defaults))

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
