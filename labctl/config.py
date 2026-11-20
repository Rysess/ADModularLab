"""Load a lab.yml and expand it into the canonical form everything else reads.

The file a user writes is short; the canonical form is explicit. Everything
that can be inferred is inferred here, once:

* ``os`` from the role (dc/child_dc/member are Windows) or the modules (vpn is Linux)
* ``role`` defaults to ``member`` for a Windows host when the lab has a controller
* ``domain`` defaults to ``lab.domain``, or to the only forest in the lab
* ``instance_type`` / ``disk_gb`` are raised to what the role and modules need
* a host running ``vpn`` gets its port exposed and source/dest check disabled
* module vars may drop their prefix: ``logon: {rdp: [x]}`` is ``logon_rdp: [x]``
* ``count: 3`` stamps out ``ws01``..``ws03``
* ``ip: 10`` is host .10 of this lab's subnet, wherever the lab is placed
* ``lab.vpn: true`` adds a VPN host

Modules may ship an ``expand.py`` next to their tasks; it runs here, so what it
generates (identity's org chart, for instance) is visible to preflight, to the
other modules, and to the walkthrough notes.
"""
import copy
import hashlib
import importlib.util
import ipaddress
import os
import re

import yaml

from .workspace import ANSIBLE

ROLES_DIR = ANSIBLE / "roles"
MODULES_DIR = ANSIBLE / "modules"

ROLE_DIR = {"dc": "dc", "member": "domain_member", "child_dc": "domain_child",
            "standalone": None}
WINDOWS_ROLES = {"dc", "child_dc", "member"}

# Memory per instance type, for min_instance_type comparisons and auto-sizing.
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
    "m7i.large": 8, "m7i.xlarge": 16,
    "c5.large": 4, "c5.xlarge": 8, "c6i.large": 4, "c6i.xlarge": 8,
    "r5.large": 16, "r6i.large": 16,
}

BUILTIN_DEFAULTS = {
    "windows_instance_type": "t3.medium",
    "linux_instance_type": "t3.micro",
    "windows_disk_gb": 50,
    "linux_disk_gb": 8,
    "windows_version": "2022",
    "windows_edition": "full",
    "ubuntu_release": "22.04",
}

LAB_KEYS = {
    "name", "region", "domain", "admin", "domain_admin", "admin_display",
    "domain_admin_display", "expires", "expires_hours", "expires_action",
    "expires_enabled", "network", "allow_from", "vpn", "imdsv1_enabled", "spot",
}
HOST_KEYS = {
    "name", "os", "role", "domain", "count", "ip", "private_ip", "instance_type",
    "type", "disk_gb", "disk", "windows_version", "version", "windows_edition",
    "edition", "ami", "source_dest_check", "expose_ports", "ports", "vars", "modules",
    "spot",
}
HOST_ALIASES = {"type": "instance_type", "disk": "disk_gb", "version": "windows_version",
                "edition": "windows_edition", "ports": "expose_ports", "ip": "private_ip"}

DEFAULT_DOMAIN = "lab.local"
DEFAULT_ADMIN = "lab.admin"
DEFAULT_EXPIRES_HOURS = 24
VPN_PORT = {"port": 1194, "proto": "udp"}


class Result:
    """What normalize() produced, plus everything it had to say about the input."""

    def __init__(self):
        self.cfg = None
        self.problems = []
        self.warnings = []
        self.notes = []       # walkthrough lines from module expanders
        self.raw = None

    @property
    def ok(self):
        return not self.problems


# --------------------------------------------------------------------------
# Role and module metadata
# --------------------------------------------------------------------------
def _yaml_file(path):
    if path.is_file():
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def component_dir(name):
    for base in (ROLES_DIR, MODULES_DIR):
        if (base / name).is_dir():
            return base / name
    return None


def meta(name):
    d = component_dir(name)
    return _yaml_file(d / "lab_meta.yml") if d else {}


def module_defaults(name):
    d = component_dir(name)
    return _yaml_file(d / "defaults" / "main.yml") if d else {}


def known_module(name):
    return (MODULES_DIR / name / "tasks" / "main.yml").is_file()


def all_modules():
    return sorted(p.name for p in MODULES_DIR.iterdir() if known_module(p.name))


def _expander(name):
    path = MODULES_DIR / name / "expand.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"adlab_expand_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "expand", None)


# --------------------------------------------------------------------------
# Small parsers
# --------------------------------------------------------------------------
def parse_hours(value, where, problems):
    """48, '48h', '2d', '1w' -> hours. None stays None."""
    if value is None:
        return None
    if isinstance(value, bool):
        problems.append(f"{where}: {value!r} is not a duration")
        return None
    if isinstance(value, int):
        hours = value
    else:
        m = re.fullmatch(r"\s*(\d+)\s*([hdw]?)\s*", str(value).lower())
        if not m:
            problems.append(f"{where}: {value!r} is not a duration like 8h, 2d or 1w")
            return None
        hours = int(m.group(1)) * {"": 1, "h": 1, "d": 24, "w": 168}[m.group(2)]
    if hours <= 0:
        problems.append(f"{where}: must be positive")
        return None
    return hours


def parse_port(entry, where, problems):
    if isinstance(entry, int):
        return {"port": entry, "proto": "tcp"}
    if isinstance(entry, str):
        m = re.fullmatch(r"(\d+)(?:/(tcp|udp))?", entry.strip().lower())
        if m:
            return {"port": int(m.group(1)), "proto": m.group(2) or "tcp"}
    if isinstance(entry, dict) and set(entry) <= {"port", "proto"}:
        return {"port": entry.get("port"), "proto": entry.get("proto", "tcp")}
    problems.append(f"{where}: expose_ports entry {entry!r} must be 3389, '1194/udp' "
                    f"or {{port, proto}}")
    return None


def network_for(index):
    return {
        "index": index,
        "vpc_cidr": f"10.{index}.0.0/16",
        "subnet_cidr": f"10.{index}.1.0/24",
        "vpn_client_cidr": f"172.16.{index}.0/24",
    }


def requested_network_index(lab, problems):
    """lab.network may be an index (20) or a 10.<n>.0.0/16 block."""
    net = lab.get("network")
    if net is None:
        return None
    if isinstance(net, int) and not isinstance(net, bool) and 0 <= net <= 254:
        return net
    m = re.fullmatch(r"10\.(\d{1,3})\.0\.0/16", str(net).strip())
    if m and int(m.group(1)) <= 254:
        return int(m.group(1))
    problems.append(f"lab.network {net!r} must be 10.<n>.0.0/16 or just <n> (0-254)")
    return None


def resolve_ip(value, subnet, where, problems):
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        host = value
    elif isinstance(value, str) and re.fullmatch(r"\.?\d{1,3}", value.strip()):
        host = int(value.strip().lstrip("."))
    else:
        try:
            addr = ipaddress.ip_address(str(value).strip())
        except ValueError:
            problems.append(f"{where}: ip {value!r} is neither an address nor a host number")
            return None
        if addr not in subnet:
            problems.append(f"{where}: ip {addr} is outside this lab's subnet {subnet}; "
                            f"write just the host number (ip: {str(addr).split('.')[-1]}) "
                            f"so it follows the lab's network")
            return None
        host = int(addr) - int(subnet.network_address)
    if not 4 <= host <= 254:
        problems.append(f"{where}: host number {host} must be 4-254 (.0-.3 and .255 are "
                        f"reserved by AWS)")
        return None
    return str(subnet.network_address + host)


def module_entries(raw, where, problems):
    """Every accepted spelling of a modules list -> [(name, vars), ...].

    - shares                      bare name
    - {name: logon, vars: {...}}  long form
    - {logon: {rdp: [x]}}         single-key form
    modules: {shares: , logon: {rdp: [x]}}   mapping form
    """
    out = []
    if raw is None:
        return out
    if isinstance(raw, dict):
        raw = [{k: v} for k, v in raw.items()]
    if not isinstance(raw, list):
        problems.append(f"{where}: modules must be a list or a mapping")
        return out
    for entry in raw:
        if isinstance(entry, str):
            out.append((entry, {}))
        elif isinstance(entry, dict) and "name" in entry:
            extra = set(entry) - {"name", "vars"}
            if extra:
                problems.append(f"{where}: module {entry['name']!r} has unknown keys "
                                f"{sorted(extra)}; expected 'name' and 'vars'")
            v = entry.get("vars") or {}
            if not isinstance(v, dict):
                problems.append(f"{where}: module {entry['name']!r} vars must be a mapping")
                v = {}
            out.append((str(entry["name"]), v))
        elif isinstance(entry, dict) and len(entry) == 1:
            (name, v), = entry.items()
            if v is None:
                v = {}
            if not isinstance(v, dict):
                problems.append(f"{where}: module {name!r} settings must be a mapping")
                v = {}
            out.append((str(name), v))
        else:
            problems.append(f"{where}: module entry {entry!r} must be a name, "
                            f"{{name, vars}} or {{<module>: {{...}}}}")
    return out


def prefix_vars(mod, mv):
    """Module vars may omit their '<module>_' prefix."""
    out = {}
    for k, v in mv.items():
        k = str(k)
        out[k if k.startswith(mod + "_") else f"{mod}_{k}"] = v
    return out


def host_list(raw_hosts, problems):
    """hosts: as a list of {name: ...} or a mapping keyed by name."""
    if isinstance(raw_hosts, dict):
        hosts = []
        for name, spec in raw_hosts.items():
            spec = dict(spec or {})
            if "name" in spec and spec["name"] != name:
                problems.append(f"hosts.{name}: 'name' {spec['name']!r} contradicts the key")
            spec["name"] = name
            hosts.append(spec)
        return hosts
    if isinstance(raw_hosts, list):
        hosts = []
        for h in raw_hosts:
            if not isinstance(h, dict):
                problems.append(f"hosts: entry {h!r} must be a mapping")
                continue
            hosts.append(dict(h))
        return hosts
    problems.append("hosts must be a list or a mapping keyed by host name")
    return []


def _stable_seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


# --------------------------------------------------------------------------
# normalize
# --------------------------------------------------------------------------
def load_yaml(path):
    with open(path, encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"{path}: {e}") from None


def normalize(raw, lab_name, network_index, default_region=None):
    """Expand a raw lab definition. Never raises on bad input: it reports."""
    r = Result()
    r.raw = raw
    p, w = r.problems, r.warnings

    if not isinstance(raw, dict):
        p.append("the lab file must be a mapping with 'lab' and 'hosts'")
        return r
    extra = set(raw) - {"lab", "defaults", "hosts"}
    if extra:
        p.append(f"unknown top-level keys {sorted(extra)}; expected lab, defaults, hosts")

    lab = dict(raw.get("lab") or {})
    unknown = set(lab) - LAB_KEYS
    if unknown:
        p.append(f"lab: unknown keys {sorted(unknown)}; expected {sorted(LAB_KEYS)}")
    if lab.get("name") not in (None, lab_name):
        p.append(f"lab.name {lab.get('name')!r} does not match the lab's directory "
                 f"{lab_name!r}; drop lab.name, the directory names the lab")

    defaults = dict(BUILTIN_DEFAULTS)
    raw_defaults = raw.get("defaults") or {}
    unknown = set(raw_defaults) - set(BUILTIN_DEFAULTS)
    if unknown:
        p.append(f"defaults: unknown keys {sorted(unknown)}; expected {sorted(BUILTIN_DEFAULTS)}")
    defaults.update({k: v for k, v in raw_defaults.items() if v is not None})
    defaults["windows_version"] = str(defaults["windows_version"])
    defaults["ubuntu_release"] = str(defaults["ubuntu_release"])

    net = network_for(network_index)
    subnet = ipaddress.ip_network(net["subnet_cidr"])

    expires_hours = parse_hours(lab.get("expires", lab.get("expires_hours")),
                                "lab.expires", p) or DEFAULT_EXPIRES_HOURS
    allow_from = lab.get("allow_from") or []
    if isinstance(allow_from, str):
        allow_from = [allow_from]
    cidrs = []
    for c in allow_from:
        try:
            n = ipaddress.ip_network(str(c), strict=False)
        except ValueError:
            p.append(f"lab.allow_from {c!r} is not an address or CIDR")
            continue
        if n.prefixlen == 0:
            p.append("lab.allow_from refuses 0.0.0.0/0: the lab runs deliberately weak AD")
            continue
        cidrs.append(str(n))

    canon_lab = {
        "name": lab_name,
        "region": str(lab.get("region") or default_region or "eu-west-3"),
        "domain_admin": str(lab.get("domain_admin") or lab.get("admin") or DEFAULT_ADMIN),
        "domain_admin_display": str(lab.get("domain_admin_display")
                                    or lab.get("admin_display")
                                    or lab.get("domain_admin") or lab.get("admin")
                                    or "Lab Administrator"),
        "expires_hours": expires_hours,
        "expires_action": str(lab.get("expires_action", "terminate")),
        "expires_enabled": lab.get("expires_enabled", True),
        "imdsv1_enabled": bool(lab.get("imdsv1_enabled", False)),
        "spot": lab.get("spot", True),
        "operator_cidrs": cidrs,
    }

    hosts = host_list(raw.get("hosts") or [], p)

    # lab.vpn: true | {name, clients, type}
    vpn = lab.get("vpn")
    if vpn:
        vspec = vpn if isinstance(vpn, dict) else {}
        unknown = set(vspec) - {"name", "clients", "type", "ip"}
        if unknown:
            p.append(f"lab.vpn: unknown keys {sorted(unknown)}; expected name, clients, type, ip")
        vname = vspec.get("name", "vpn01")
        already = any(n == "vpn" for h in hosts
                      for n, _ in module_entries(h.get("modules"), "", []))
        if not already:
            mv = {"clients": vspec["clients"]} if "clients" in vspec else {}
            h = {"name": vname, "os": "linux", "role": "standalone",
                 "modules": [{"vpn": mv}]}
            if "type" in vspec:
                h["instance_type"] = vspec["type"]
            if "ip" in vspec:
                h["ip"] = vspec["ip"]
            hosts.append(h)

    # count: N -> name01..nameN
    expanded = []
    for h in hosts:
        count = h.pop("count", None)
        if count is None:
            expanded.append(h)
            continue
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 50:
            p.append(f"{h.get('name')}: count {count!r} must be 1-50")
            continue
        base_ip = h.get("ip", h.get("private_ip"))
        for i in range(1, count + 1):
            c = copy.deepcopy(h)
            c["name"] = f"{h.get('name')}{i:02d}"
            if base_ip is not None:
                c.pop("private_ip", None)
                c["ip"] = (base_ip + i - 1) if isinstance(base_ip, int) else base_ip
                if not isinstance(base_ip, int):
                    p.append(f"{h.get('name')}: with count, ip must be a host number")
            expanded.append(c)
    hosts = expanded

    # Pass 1: names, aliases, roles and OS, so domain inference sees the whole lab.
    staged = []
    for h in hosts:
        name = str(h.get("name", ""))
        where = name or "<unnamed host>"
        unknown = set(h) - HOST_KEYS
        if unknown:
            p.append(f"{where}: unknown keys {sorted(unknown)}")
        for alias, real in HOST_ALIASES.items():
            if alias in h:
                if real in h:
                    p.append(f"{where}: set either {alias!r} or {real!r}, not both")
                h[real] = h.pop(alias)
        mods = module_entries(h.get("modules"), where, p)
        staged.append((h, mods))

    has_dc = any(h.get("role") == "dc" for h, _ in staged)
    for h, mods in staged:
        where = h.get("name") or "<unnamed host>"
        if "os" not in h:
            if h.get("role") in WINDOWS_ROLES:
                h["os"] = "windows"
            else:
                oses = {meta(m).get("os") for m, _ in mods} - {None, "any"}
                if len(oses) == 1:
                    h["os"] = oses.pop()
                elif len(oses) > 1:
                    p.append(f"{where}: its modules need both Windows and Linux")
                elif has_dc or h.get("role") is None:
                    h["os"] = "windows"
        if "role" not in h:
            h["role"] = "member" if h.get("os") == "windows" and has_dc else "standalone"

    lab_domain = lab.get("domain")
    for h, _ in staged:
        if h.get("role") == "dc" and not h.get("domain"):
            h["domain"] = lab_domain or DEFAULT_DOMAIN
    forests = sorted({h.get("domain") for h, _ in staged
                      if h.get("role") == "dc" and h.get("domain")})
    default_domain = lab_domain or (forests[0] if len(forests) == 1 else None)

    # Pass 2: everything else.
    canon_hosts = []
    for h, mods in staged:
        name = str(h.get("name", ""))
        where = name or "<unnamed host>"
        os_ = h.get("os")
        role = h.get("role")

        domain = h.get("domain")
        if domain is None and role in ("dc", "member"):
            domain = default_domain or (DEFAULT_DOMAIN if role == "dc" else None)
            if domain is None and role == "member":
                if forests:
                    p.append(f"{where}: the lab has several forests ({', '.join(forests)}); "
                             f"say which one this member joins with 'domain'")
                else:
                    p.append(f"{where}: role member needs a domain controller in the lab")
        if role == "child_dc" and not domain:
            p.append(f"{where}: a child_dc must name its domain, as in child.{default_domain or DEFAULT_DOMAIN}")

        ports = []
        for e in h.get("expose_ports") or []:
            pe = parse_port(e, where, p)
            if pe:
                ports.append(pe)

        mod_names = [m for m, _ in mods]
        if "vpn" in mod_names:
            if VPN_PORT not in ports:
                ports.append(dict(VPN_PORT))
            if h.get("source_dest_check") is True:
                p.append(f"{where}: runs vpn, so source_dest_check must stay false")
            h["source_dest_check"] = False

        edition = str(h.get("windows_edition", defaults["windows_edition"]))
        components = ([ROLE_DIR[role]] if ROLE_DIR.get(role) else []) + mod_names

        itype = h.get("instance_type")
        explicit_type = itype is not None
        if itype is None and os_ in ("windows", "linux"):
            itype = defaults[f"{os_}_instance_type"]
            for c in components:
                m = meta(c)
                need = m.get("min_instance_type_core", m.get("min_instance_type")) \
                    if edition == "core" else m.get("min_instance_type")
                if need and MEM.get(need, 0) > MEM.get(itype, 0):
                    itype = need

        disk = h.get("disk_gb")
        if disk is None and os_ in ("windows", "linux"):
            disk = defaults[f"{os_}_disk_gb"]
            for c in components:
                need = meta(c).get("min_disk_gb")
                if need and need > disk:
                    disk = need

        ip = resolve_ip(h.get("private_ip"), subnet, where, p)

        host_vars = h.get("vars") or {}
        if not isinstance(host_vars, dict):
            p.append(f"{where}: 'vars' must be a mapping")
            host_vars = {}

        canon_mods = [{"name": m, "vars": prefix_vars(m, mv)} for m, mv in mods]

        ch = {
            "name": name,
            "os": os_,
            "role": role,
            "domain": domain,
            "instance_type": itype,
            "instance_type_explicit": explicit_type,
            "disk_gb": disk,
            "private_ip": ip,
            "ami": h.get("ami"),
            "source_dest_check": bool(h.get("source_dest_check", True)),
            "spot": h.get("spot", canon_lab["spot"]),
            "expose_ports": ports,
            "vars": host_vars,
            "modules": canon_mods,
        }
        if os_ == "windows":
            ch["windows_version"] = str(h.get("windows_version", defaults["windows_version"]))
            ch["windows_edition"] = edition
        elif "windows_version" in h or "windows_edition" in h:
            p.append(f"{where}: windows_version/windows_edition only apply to Windows hosts")
        canon_hosts.append(ch)

    cfg = {
        "lab": canon_lab,
        "defaults": defaults,
        "network": net,
        "hosts": canon_hosts,
    }

    # Module expanders run last, against the whole lab: controllers first, so a
    # module elsewhere can refer to what identity generated.
    order = sorted(canon_hosts, key=lambda h: h["role"] not in ("dc", "child_dc"))
    for h in order:
        for m in h["modules"]:
            fn = _expander(m["name"]) if known_module(m["name"]) else None
            if not fn:
                continue
            ctx = ExpandContext(cfg, h, m["name"], r)
            try:
                out = fn(dict(m["vars"]), ctx)
            except ExpandError as e:
                p.append(f"{h['name']}: module {m['name']!r}: {e}")
                continue
            if out is not None:
                m["vars"] = out

    # Ansible sees one merged var set per host: module vars, then host vars.
    for h in canon_hosts:
        av = {}
        for m in h["modules"]:
            av.update(m["vars"])
        av.update(h["vars"])
        if h["domain"]:
            av["domain_name"] = h["domain"]
        h["ansible_vars"] = av

    r.cfg = cfg
    return r


class ExpandError(Exception):
    pass


class ExpandContext:
    """What a module's expand(vars, ctx) may look at."""

    def __init__(self, cfg, host, module, result):
        self.cfg = cfg
        self.host = host
        self.module = module
        self._result = result
        self.defaults = module_defaults(module)

    @property
    def lab_name(self):
        return self.cfg["lab"]["name"]

    def seed(self, *parts):
        return _stable_seed(self.lab_name, self.host["name"], self.module, *parts)

    def warn(self, msg):
        self._result.warnings.append(f"{self.host['name']}: module {self.module!r}: {msg}")

    def note(self, msg):
        self._result.notes.append((self.host["name"], self.module, msg))

    def hosts(self):
        return self.cfg["hosts"]

    def module_vars(self, module, domain=None):
        """Expanded vars of `module` on the controller of `domain` (this host's by default)."""
        domain = domain or self.host["domain"]
        for h in self.cfg["hosts"]:
            if h["role"] in ("dc", "child_dc") and h["domain"] == domain:
                for m in h["modules"]:
                    if m["name"] == module:
                        return m["vars"]
        return None


def tf_input(cfg, expires_at):
    """The subset Terraform consumes, JSON-ready."""
    return {
        "lab": {**cfg["lab"], "expires_at": expires_at},
        "network": cfg["network"],
        "defaults": cfg["defaults"],
        "hosts": [{
            "name": h["name"], "os": h["os"], "role": h["role"], "domain": h["domain"] or "",
            "instance_type": h["instance_type"], "disk_gb": h["disk_gb"],
            "private_ip": h["private_ip"] or "", "ami": h["ami"] or "",
            "source_dest_check": h["source_dest_check"],
            "spot": bool(h["spot"]),
            "expose_ports": h["expose_ports"],
            "windows_version": h.get("windows_version", ""),
            "windows_edition": h.get("windows_edition", ""),
            "modules": [m["name"] for m in h["modules"]],
        } for h in cfg["hosts"]],
    }


def summary(cfg):
    """{host: {...}} used to diff what is deployed against what is declared."""
    return {h["name"]: {
        "os": h["os"], "role": h["role"], "domain": h["domain"],
        "instance_type": h["instance_type"], "disk_gb": h["disk_gb"],
        "private_ip": h["private_ip"],
        "spot": bool(h["spot"]),
        "windows_version": h.get("windows_version"),
        "windows_edition": h.get("windows_edition"),
        "modules": [m["name"] for m in h["modules"]],
    } for h in cfg["hosts"]}


def default_region():
    for env in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        if os.environ.get(env):
            return os.environ[env]
    try:
        import boto3
        return boto3.session.Session().region_name
    except Exception:  # noqa: BLE001 - any failure just means "no default"
        return None
