"""./lab build - put a lab together interactively.

Start from an empty lab (or an existing one), add hosts one question at a time,
pick modules from the ones that fit, and see the lab validate as you go. Every
list is filterable: start typing to narrow it, like Ctrl+R in a shell.
"""
import re
import sys

import yaml
from ruamel.yaml.comments import CommentedMap

from . import config, edit, preflight
from .workspace import LabError, Workspace, all_labs

ROLE_CHOICES = [
    ("dc", "Domain controller", "promotes a new forest root"),
    ("member", "Member", "a server or workstation joined to a domain"),
    ("child_dc", "Child domain controller", "a child domain under an existing forest"),
    ("standalone", "Standalone", "no domain: a VPN box, a Linux tool host, an Elastic server"),
]
NAME_PREFIX = {"dc": "dc", "child_dc": "dc", "member": "srv", "standalone": "box"}
INSTANCE_TYPES = ["t3.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge",
                  "t3a.medium", "t3a.large", "m6i.large"]

# Settings that are plumbing, not choices.
HIDDEN_SETTING = re.compile(r"(_retries|_delay|_timeout|_dir|_dc_host|_service|_exe|_port"
                            r"|_workdir|_secret_dir|_probe_container)$")
HIDDEN_KEYS = {"logon_local_groups", "logon_rights", "identity_domain", "identity_domain_dn",
               "shares_decoy_files", "vpn_client_name", "identity_users", "identity_groups"}

# List settings whose entries are AD principals: offered as a pick list.
PRINCIPAL_LISTS = {
    "logon_admins", "logon_rdp", "logon_interactive", "logon_batch",
    "logon_deny_interactive", "logon_deny_rdp", "logon_deny_network",
    "laps_read_principals", "vulns_dcsync_principals", "vulns_asreproast_users",
    "gmsa_principals", "vulns_unconstrained_delegation_computers",
}

# Asked when a module is added; everything else stays at its default unless edited.
QUICK = {
    "session": [("user", "Account to log on at the console", "principal-one", True)],
    "identity": [("generate", "How many generated staff?", "int", False),
                 ("weak_passwords", "How many with a sprayable password?", "int", False)],
    "logon": [("rdp", "Who may RDP in?", "principals", False),
              ("admins", "Who are local administrators?", "principals", False)],
    "vpn": [("clients", "VPN client profile names (YAML list)", "yaml", False)],
    "trust": [("partners", "Trust partners", "trust", True)],
    "laps": [("read_principals", "Who may read LAPS passwords? (beyond Domain Admins)",
              "principals", False)],
}

WELL_KNOWN_GROUPS = ["Domain Users", "Domain Admins", "Domain Computers", "Authenticated Users",
                     "Everyone", "Enterprise Admins", "Backup Operators", "Server Operators",
                     "Account Operators", "Remote Desktop Users", "DnsAdmins"]


# --------------------------------------------------------------------------
# UI: questionary in a terminal; scripted in tests.
# --------------------------------------------------------------------------
class Back(Exception):
    """Esc / Ctrl+C on a prompt: go back one level."""


class TerminalUI:
    def __init__(self):
        try:
            import questionary
        except ImportError:
            raise LabError("the builder needs questionary: venv/bin/pip install -r "
                           "requirements.txt") from None
        if not sys.stdin.isatty():
            raise LabError("./lab build is interactive; run it in a terminal")
        # Some terminals (tmux, older emulators) never answer cursor-position
        # queries; prompt_toolkit then prints a warning in the middle of the menu.
        import os
        os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
        self.q = questionary
        self.style = questionary.Style([("qmark", "fg:#5f87ff bold"), ("pointer", "fg:#5f87ff bold"),
                                        ("highlighted", "fg:#5f87ff bold"), ("answer", "fg:#87d787"),
                                        ("instruction", "fg:#808080")])

    def _ask(self, prompt):
        ans = prompt.ask()
        if ans is None:
            raise Back()
        return ans

    def _choices(self, choices):
        return [self.q.Choice(title=t, value=v, description=d or None) for t, v, d in choices]

    def select(self, msg, choices, default=None):
        """choices: [(title, value, description)]"""
        cs = self._choices(choices)
        dflt = next((c for c in cs if c.value == default), None)
        return self._ask(self.q.select(msg, cs, default=dflt, use_search_filter=True,
                                       use_jk_keys=False, show_description=True,
                                       instruction="(type to filter)", style=self.style))

    def checkbox(self, msg, choices, checked=()):
        cs = [self.q.Choice(title=t, value=v, description=d or None, checked=v in checked)
              for t, v, d in choices]
        return self._ask(self.q.checkbox(msg, cs, use_search_filter=True, use_jk_keys=False,
                                         show_description=True, style=self.style,
                                         instruction="(space toggles, type to filter, enter done)"))

    def text(self, msg, default="", validate=None):
        def check(s):
            err = validate(s) if validate else None
            return True if err is None else err
        return self._ask(self.q.text(msg, default=str(default), style=self.style, validate=check))

    def confirm(self, msg, default=True):
        return self._ask(self.q.confirm(msg, default=default, style=self.style))

    def echo(self, text=""):
        print(text, flush=True)


# --------------------------------------------------------------------------
# Builder
# --------------------------------------------------------------------------
class Builder:
    def __init__(self, ws, ui):
        self.ws = ws
        self.ui = ui
        if ws.exists():
            self.y, self.data = edit.load(ws.lab_file)
        else:
            self.y = edit._yaml()
            self.data = CommentedMap()
            self.data["lab"] = CommentedMap([("domain", "lab.local"), ("expires", "24h")])
            self.data["hosts"] = CommentedMap()
            self.data.yaml_set_start_comment(f"Lab {ws.name}, built with ./lab build")
        if self.data.get("hosts") is None:
            self.data["hosts"] = CommentedMap()
        self.dirty = not ws.exists()

    # -- state ----------------------------------------------------------------
    def raw(self):
        return yaml.safe_load(edit.dump(self.y, self.data)) or {}

    def resolve(self):
        idx = self.ws.state().get("network_index", 10)
        r = config.normalize(self.raw(), self.ws.name, idx, config.default_region())
        if r.ok:
            p, w = preflight.run(r.cfg)
            r.problems += p
            r.warnings += w
        return r

    def lab(self):
        if self.data.get("lab") is None:
            self.data["lab"] = CommentedMap()
        return self.data["lab"]

    def host_names(self):
        r = self.resolve()
        return [h["name"] for h in r.cfg["hosts"]] if r.cfg else []

    def declared(self):
        """Hosts as written (names before count expansion), with their nodes."""
        hosts = self.data["hosts"]
        if isinstance(hosts, dict):
            return list(hosts.items())
        return [(h.get("name"), h) for h in hosts if isinstance(h, dict)]

    def principals(self, domain=None):
        r = self.resolve()
        names = list(WELL_KNOWN_GROUPS)
        if not r.cfg:
            return names
        names.append(r.cfg["lab"]["domain_admin"])
        names += [f"LabUser{i}" for i in range(1, 11)]
        for h in r.cfg["hosts"]:
            for m in h["modules"]:
                if m["name"] == "identity" and (domain is None or h["domain"] == domain):
                    names += list(m["vars"].get("identity_groups", {}))
                    names += list(m["vars"].get("identity_users", {}))
        names += [h["name"] for h in r.cfg["hosts"]]
        seen, out = set(), []
        for n in names:
            if n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
        return out

    def admins(self):
        r = self.resolve()
        out = []
        for h in (r.cfg or {}).get("hosts", []):
            for m in h["modules"]:
                if m["name"] == "identity":
                    out += m["vars"].get("identity_generated_admins", [])
        return out

    # -- display ---------------------------------------------------------------
    def show(self):
        r = self.resolve()
        ui = self.ui
        lab = self.lab()
        ui.echo("")
        ui.echo(f"\033[1mLab {self.ws.name}\033[0m  domain={lab.get('domain', 'lab.local')}  "
                f"expires={lab.get('expires', '24h')}  vpn={'on' if lab.get('vpn') else 'off'}"
                f"{'  (unsaved)' if self.dirty else ''}")
        if r.cfg and r.cfg["hosts"]:
            for h in r.cfg["hosts"]:
                ui.echo(f"  {h['name']:<14} {h['role']:<10} {h['os']:<8} {(h['domain'] or '-'):<18} "
                        f"{h['instance_type']:<10} {', '.join(m['name'] for m in h['modules']) or '-'}")
        else:
            ui.echo("  (no hosts yet)")
        for w in r.warnings:
            ui.echo(f"  \033[33mwarn\033[0m {w}")
        for p in r.problems:
            ui.echo(f"  \033[31m✗\033[0m {p}")
        if r.ok and r.cfg and r.cfg["hosts"]:
            ui.echo("  \033[32m✓ valid\033[0m")
        ui.echo("")
        return r

    # -- main loop ---------------------------------------------------------------
    def run(self):
        while True:
            r = self.show()
            hosts = self.declared()
            choices = [("+ Add a host", "add", "a domain controller, a member, a standalone box")]
            choices += [(f"  Edit {name}", ("edit", name), "modules, settings, size, address")
                        for name, _ in hosts]
            choices += [
                ("⚙ Lab settings", "lab", "domain, admin, expiry, VPN, region"),
                ("◎ Preview what this expands to", "preview", "the full canonical definition"),
                ("✓ Save", "save", str(self.ws.lab_file)),
                ("▶ Save and deploy", "deploy", f"./lab up {self.ws.name}"),
                ("✗ Quit", "quit", "unsaved changes are lost" if self.dirty else ""),
            ]
            try:
                action = self.ui.select("What next?", choices)
            except Back:
                action = "quit"
            try:
                if action == "add":
                    self.add_host()
                elif isinstance(action, tuple):
                    self.edit_host(action[1])
                elif action == "lab":
                    self.lab_settings()
                elif action == "preview":
                    self.ui.echo(yaml.safe_dump(r.cfg, sort_keys=False, width=100)
                                 if r.cfg else "\n".join(r.problems))
                elif action == "save":
                    self.save()
                elif action == "deploy":
                    if self.save():
                        return "deploy"
                elif action == "quit":
                    if not self.dirty or self.ui.confirm("Quit without saving?", default=False):
                        return "quit"
            except Back:
                continue

    # -- saving ------------------------------------------------------------------
    def save(self):
        r = self.resolve()
        if not r.ok and not self.ui.confirm(f"The lab has {len(r.problems)} problem(s). "
                                            f"Save anyway?", default=False):
            return False
        from .workspace import atomic_write
        self.ws.dir.mkdir(parents=True, exist_ok=True)
        atomic_write(self.ws.lab_file, edit.dump(self.y, self.data))
        self.dirty = False
        self.ui.echo(f"saved {self.ws.lab_file}")
        return r.ok

    # -- hosts -------------------------------------------------------------------
    def add_host(self):
        r = self.resolve()
        hosts = r.cfg["hosts"] if r.cfg else []
        forests = sorted({h["domain"] for h in hosts if h["role"] == "dc"})
        domains = sorted({h["domain"] for h in hosts if h["role"] in ("dc", "child_dc")})

        roles = [(f"{t}", v, d) for v, t, d in ROLE_CHOICES
                 if v in ("dc", "standalone") or forests]
        role = self.ui.select("What kind of host?", roles,
                              default="dc" if not forests else "member")

        spec = CommentedMap()
        os_ = "windows"
        if role == "standalone":
            os_ = self.ui.select("Operating system?", [
                ("Windows Server", "windows", "a non-domain Windows box"),
                ("Ubuntu Linux", "linux", "VPN, Elastic, attacker tooling")])
        spec["role"] = role
        if role == "standalone":
            spec["os"] = os_

        # Name
        taken = {n.lower() for n in self.host_names()}
        prefix = NAME_PREFIX[role] if not (role == "standalone" and os_ == "linux") else "lin"
        n = 1
        while f"{prefix}{n:02d}" in taken:
            n += 1

        def valid_name(s):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,14}", s):
                return "1-15 letters, digits or '-'"
            if s.lower() in taken:
                return "a host already has that name"
            return None
        name = self.ui.text("Host name?", f"{prefix}{n:02d}", valid_name)

        # Domain
        if role == "dc":
            default = self.lab().get("domain", "lab.local") if not forests else "partner.local"
            spec["domain"] = self.ui.text(
                "Domain this controller creates?", default,
                lambda s: None if re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", s)
                else "a dotted DNS name, e.g. lab.local")
        elif role == "child_dc":
            parent = forests[0]
            spec["domain"] = self.ui.text("Child domain?", f"child.{parent}",
                                          lambda s: None if s.split(".", 1)[-1] in forests
                                          else f"must sit under one of {', '.join(forests)}")
        elif role == "member" and len(domains) > 1:
            spec["domain"] = self.ui.select("Join which domain?",
                                            [(d, d, "") for d in domains])

        # OS version
        if os_ == "windows":
            ver = self.ui.select("Windows Server version?", [
                ("2022 (default)", "2022", ""), ("2025", "2025", "newest; stricter defaults"),
                ("2019", "2019", ""), ("2016", "2016", "oldest still on AWS")], default="2022")
            if ver != "2022":
                spec["version"] = ver
            ed = self.ui.select("Edition?", [
                ("Desktop Experience (default)", "full", "a GUI; needed to see a console session"),
                ("Core", "core", "no GUI, smaller instance, faster boot")], default="full")
            if ed != "full":
                spec["edition"] = ed

        # How many
        if role in ("member", "standalone"):
            count = self.ui.text("How many of these? (1 for a single host)", "1",
                                 lambda s: None if s.isdigit() and 1 <= int(s) <= 50 else "1-50")
            if int(count) > 1:
                spec["count"] = int(count)
                if re.search(r"\d\d$", name):
                    name = name[:-2]

        # Modules
        mods = self.pick_modules(role, os_, spec.get("domain"), [])
        if mods:
            spec["modules"] = CommentedMap()
            for m in mods:
                spec["modules"][m] = self.quick_settings(m, spec.get("domain")) or None

        # Size and address
        size = self.ui.select("Instance size?", [("auto: sized from its role and modules",
                                                  "auto", "")] +
                              [(t, t, "") for t in INSTANCE_TYPES], default="auto")
        if size != "auto":
            spec["type"] = size
        ip = self.ui.text("Address in the lab subnet? (host number, empty = any)", "",
                          lambda s: None if s == "" or (s.isdigit() and 4 <= int(s) <= 254)
                          else "4-254, or empty")
        if ip:
            spec["ip"] = int(ip)

        edit.add_host(self.data, name, spec)
        self.dirty = True

    def compatible_modules(self, role, os_):
        out = []
        for m in config.all_modules():
            meta = config.meta(m)
            mos = meta.get("os", "any")
            if mos not in ("any", os_):
                continue
            req = meta.get("requires_role")
            if req and role not in (req if isinstance(req, list) else [req]):
                continue
            out.append(m)
        return out

    def module_description(self, m):
        readme = config.MODULES_DIR / m / "README.md"
        if readme.exists():
            for line in readme.read_text().splitlines()[1:]:
                if line.strip():
                    return re.sub(r"[*`]", "", line.strip())[:110]
        return ""

    def pick_modules(self, role, os_, domain, current):
        mods = self.compatible_modules(role, os_)
        if not mods:
            return []
        return self.ui.checkbox("Modules to run on it?",
                                [(m, m, self.module_description(m)) for m in mods],
                                checked=current)

    def quick_settings(self, module, domain):
        out = CommentedMap()
        for key, question, kind, required in QUICK.get(module, []):
            v = self.ask_value(module, key, question, kind, domain, required)
            default = config.module_defaults(module).get(f"{module}_{key}")
            if v not in (None, [], "") and v != default:
                out[key] = v
        return out

    def ask_value(self, module, key, question, kind, domain, required=False, current=None):
        if kind == "int":
            dflt = current if current is not None else config.module_defaults(module).get(f"{module}_{key}", 0)
            s = self.ui.text(question, str(dflt), lambda s: None if s.lstrip("-").isdigit() else "a number")
            return int(s)
        if kind == "bool":
            return self.ui.select(question, [("yes", True, ""), ("no", False, "")],
                                  default=bool(current))
        if kind == "principals":
            return self.ui.checkbox(question, [(p, p, "") for p in self.principals(domain)],
                                    checked=current or [])
        if kind == "principal-one":
            choices = [(f"@admin ({a})" if i == 0 else f"@admin{i + 1} ({a})",
                        "@admin" if i == 0 else f"@admin{i + 1}",
                        "a Domain Admin generated by identity")
                       for i, a in enumerate(self.admins())]
            choices += [(p, p, "") for p in self.principals(domain) if p not in WELL_KNOWN_GROUPS]
            choices.append(("(type another account)", "__other__", ""))
            v = self.ui.select(question, choices, default=current)
            if v == "__other__":
                v = self.ui.text("sAMAccountName?", current or "")
            return v
        if kind == "trust":
            r = self.resolve()
            others = sorted({h["domain"] for h in (r.cfg or {}).get("hosts", [])
                             if h["role"] == "dc" and h["domain"] != domain})
            if not others:
                self.ui.echo("  no other forest in the lab yet; add a second dc first")
                return None
            picked = self.ui.checkbox("Trust which forests?", [(d, d, "") for d in others])
            return [{"name": d} for d in picked]
        # yaml
        text = self.ui.text(f"{question} (YAML, empty = default)",
                            "" if current is None else yaml.safe_dump(current, default_flow_style=True).strip())
        if text.strip() == "":
            return None
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as e:
            self.ui.echo(f"  not valid YAML: {e}")
            return self.ask_value(module, key, question, kind, domain, required, current)

    # -- editing ----------------------------------------------------------------
    def _node(self, name):
        node, how = edit._find(self.data, name)
        if node is None:
            raise LabError(f"{name} cannot be edited here; edit lab.yml")
        return node

    def _mods_map(self, node):
        """The host's modules as a mapping, converting a list in place."""
        mods = node.get("modules")
        if isinstance(mods, dict):
            return mods
        m = CommentedMap()
        for e in mods or []:
            if isinstance(e, str):
                m[e] = None
            elif isinstance(e, dict) and "name" in e:
                m[e["name"]] = e.get("vars")
            elif isinstance(e, dict):
                (k, v), = e.items()
                m[k] = v
        node["modules"] = m
        return m

    def edit_host(self, name):
        while True:
            node = self._node(name)
            r = self.resolve()
            h = next((x for x in (r.cfg or {}).get("hosts", [])
                      if x["name"] == name or re.fullmatch(re.escape(name) + r"\d\d", x["name"])), None)
            mods = self._mods_map(node)
            choices = [("Modules", "modules", ", ".join(mods) or "none")]
            choices += [(f"  Settings of {m}", ("settings", m), "") for m in mods]
            choices += [("Size", "size", h["instance_type"] if h else ""),
                        ("Address", "ip", str(node.get("ip", node.get("private_ip", "any")))),
                        ("Remove this host", "remove", ""),
                        ("← Back", "back", "")]
            action = self.ui.select(f"Edit {name}", choices)
            if action == "back":
                return
            if action == "modules":
                role = h["role"] if h else node.get("role", "member")
                os_ = h["os"] if h else node.get("os", "windows")
                picked = self.pick_modules(role, os_, h["domain"] if h else None, list(mods))
                for m in [m for m in mods if m not in picked]:
                    del mods[m]
                for m in picked:
                    if m not in mods:
                        mods[m] = self.quick_settings(m, h["domain"] if h else None) or None
                self.dirty = True
            elif isinstance(action, tuple):
                self.module_settings(node, action[1], h["domain"] if h else None)
            elif action == "size":
                size = self.ui.select("Instance size?", [("auto", "auto", "")] +
                                      [(t, t, "") for t in INSTANCE_TYPES])
                for k in ("type", "instance_type"):
                    node.pop(k, None)
                if size != "auto":
                    node["type"] = size
                self.dirty = True
            elif action == "ip":
                ip = self.ui.text("Host number (empty = any)", "",
                                  lambda s: None if s == "" or (s.isdigit() and 4 <= int(s) <= 254)
                                  else "4-254, or empty")
                for k in ("ip", "private_ip"):
                    node.pop(k, None)
                if ip:
                    node["ip"] = int(ip)
                self.dirty = True
            elif action == "remove":
                if self.ui.confirm(f"Remove {name} from the lab?", default=False):
                    edit.remove_host(self.data, name)
                    self.dirty = True
                    return

    def settings_of(self, module):
        """(short key, default) pairs a user may sensibly change."""
        out = []
        for k, v in config.module_defaults(module).items():
            if not k.startswith(module + "_") or k in HIDDEN_KEYS or HIDDEN_SETTING.search(k):
                continue
            if isinstance(v, str) and "{{" in v:
                continue
            out.append((k[len(module) + 1:], v))
        return out

    def module_settings(self, node, module, domain):
        mods = self._mods_map(node)
        while True:
            cur = mods.get(module) or CommentedMap()
            choices = []
            for key, dflt in self.settings_of(module):
                full = f"{module}_{key}"
                val = cur.get(key, cur.get(full))
                shown = val if val is not None else dflt
                text = yaml.safe_dump(shown, default_flow_style=True, width=60).strip()
                if text.endswith("\n..."):
                    text = text[:-4]
                text = text.replace("\n...", "")
                mark = "●" if val is not None else " "
                choices.append((f"{mark} {key} = {text[:60]}", key,
                                "set" if val is not None else "default"))
            choices.append(("← Back", "__back__", ""))
            key = self.ui.select(f"{module} settings (● = set here)", choices)
            if key == "__back__":
                return
            dflt = dict(self.settings_of(module))[key]
            current = cur.get(key, cur.get(f"{module}_{key}"))
            full = f"{module}_{key}"
            if full in PRINCIPAL_LISTS:
                kind = "principals"
            elif isinstance(dflt, bool):
                kind = "bool"
            elif isinstance(dflt, int):
                kind = "int"
            else:
                kind = "yaml"
            v = self.ask_value(module, key, key, kind, domain,
                               current=current if current is not None else (dflt if kind != "yaml" else None))
            cur.pop(full, None)
            if v is None or v == dflt:
                cur.pop(key, None)
            else:
                cur[key] = v
            mods[module] = cur or None
            self.dirty = True

    # -- lab ---------------------------------------------------------------------
    def lab_settings(self):
        while True:
            lab = self.lab()
            vpn = lab.get("vpn")
            choices = [
                ("Default domain", "domain", str(lab.get("domain", "lab.local"))),
                ("Domain admin account", "admin", str(lab.get("admin", lab.get("domain_admin", "lab.admin")))),
                ("Expires after", "expires", str(lab.get("expires", "24h"))),
                ("When it expires", "expires_action", str(lab.get("expires_action", "terminate"))),
                ("VPN", "vpn", "on" if vpn else "off"),
                ("Region", "region", str(lab.get("region", config.default_region() or "eu-west-3"))),
                ("← Back", "back", ""),
            ]
            k = self.ui.select("Lab settings", choices)
            if k == "back":
                return
            if k == "vpn":
                on = self.ui.select("VPN access?", [
                    ("on", True, "adds a small Linux OpenVPN host ($0.01/h)"),
                    ("off", False, "reach hosts over their public IPs")], default=bool(vpn))
                if on:
                    clients = self.ui.text("Client profiles (comma separated)",
                                           ",".join((vpn or {}).get("clients", ["client1"]))
                                           if isinstance(vpn, dict) else "client1")
                    names = [c.strip() for c in clients.split(",") if c.strip()]
                    lab["vpn"] = True if names == ["client1"] else CommentedMap([("clients", names)])
                else:
                    lab["vpn"] = False
            elif k == "expires_action":
                lab[k] = self.ui.select("When the lab expires", [
                    ("terminate", "terminate", "delete the instances"),
                    ("stop", "stop", "stop them, keep the disks")])
            elif k == "expires":
                lab["expires"] = self.ui.text(
                    "Expires after (8h, 2d, 1w)", str(lab.get("expires", "24h")),
                    lambda s: None if config.parse_hours(s, "", []) else "like 8h, 2d or 1w")
            else:
                title, _, current = next(c for c in choices if c[1] == k)
                if k == "admin":
                    lab.pop("domain_admin", None)
                lab[k] = self.ui.text(title, current)
            self.dirty = True


def pick_lab(ui):
    labs = all_labs()
    choices = [("+ New lab", "__new__", "start from an empty lab")]
    choices += [(n, n, "edit") for n in labs]
    name = ui.select("Which lab?", choices)
    if name == "__new__":
        name = ui.text("Name for the new lab?", "",
                       lambda s: None if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", s) and s not in labs
                       else "lowercase letters, digits, '-'; not an existing lab")
    return name


def run_builder(name=None, ui=None):
    ui = ui or TerminalUI()
    try:
        name = name or pick_lab(ui)
    except Back:
        return None, "quit"
    ws = Workspace(name)
    b = Builder(ws, ui)
    return ws, b.run()
