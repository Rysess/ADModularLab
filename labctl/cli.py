"""./lab - deploy, update and tear down AD labs, any number at a time.

Run ./lab --help, or ./lab <command> --help.
"""
import argparse
import contextlib
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

import yaml

from . import config, edit, preflight
from .runner import (SPOT_CAPACITY_ERRORS, Ansible, Runner, Terraform, best_spot_zone,
                     cancel_spot_requests, check_aws, ec2, instances, untracked_labs,
                     used_network_indexes, write_inventory)
from .workspace import (EXAMPLES, LABS, ROOT, TERRAFORM, LabError, Workspace, all_labs,
                        atomic_write, iso, parse_iso, utcnow)

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    ("\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m")
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else ("",) * 6)


def info(msg):
    print(f"{BOLD}[lab]{RESET} {msg}", flush=True)


def warn(msg):
    print(f"{YELLOW}[warn]{RESET} {msg}", flush=True)


def confirm(question, assume_yes):
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise LabError(f"{question} - refusing without a terminal; pass -y to confirm")
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------
# Loading and validating
# --------------------------------------------------------------------------
def resolve(ws, raw=None, quiet=False):
    """lab.yml -> canonical config, validated. Raises LabError on problems."""
    if raw is None:
        try:
            raw = config.load_yaml(ws.lab_file)
        except ValueError as e:
            raise LabError(str(e)) from None
    lab = (raw or {}).get("lab") or {} if isinstance(raw, dict) else {}
    early = []
    idx = config.requested_network_index(lab, early)
    if early:
        raise LabError("\n  - ".join([f"{ws.lab_file} is invalid:"] + early))
    region = str(lab.get("region") or config.default_region() or "eu-west-3")
    idx = ws.network_index(idx, taken=lambda: used_network_indexes(region))
    r = config.normalize(raw, ws.name, idx, config.default_region())
    if r.ok:
        problems, warns = preflight.run(r.cfg)
        r.problems += problems
        r.warnings += warns
    if not quiet:
        for w in r.warnings:
            warn(w)
    if r.problems:
        raise LabError("\n  - ".join([f"{ws.lab_file} is invalid:"] + r.problems))
    return r


def expiry_for(ws, cfg, extend=None):
    """RFC3339 expiry to deploy with: kept across runs, unless extended or lapsed."""
    if not cfg["lab"]["expires_enabled"]:
        return "never"
    st = ws.state()
    if extend == "never":
        return "never"
    if extend:
        return iso(utcnow() + dt.timedelta(hours=extend))
    cur = st.get("expires_at")
    if cur == "never":
        return cur
    if cur and parse_iso(cur) > utcnow():
        return cur
    return iso(utcnow() + dt.timedelta(hours=cfg["lab"]["expires_hours"]))


def describe_expiry(value):
    if value == "never":
        return "never (no expiry Lambda)"
    t = parse_iso(value)
    left = t - utcnow()
    if left.total_seconds() <= 0:
        return f"{value} ({RED}expired{RESET})"
    h = int(left.total_seconds() // 3600)
    return f"{value} (in {h // 24}d {h % 24}h)" if h >= 24 else f"{value} (in {h}h {int(left.total_seconds() % 3600 // 60)}m)"


def plan_diff(old, new):
    """Human summary of declared changes between two config summaries."""
    lines = []
    for h in sorted(set(new) - set(old)):
        lines.append(f"  + host {h} ({new[h]['role']}, {', '.join(new[h]['modules']) or 'no modules'})")
    for h in sorted(set(old) - set(new)):
        lines.append(f"  - host {h}")
    for h in sorted(set(old) & set(new)):
        a, b = old[h], new[h]
        added = [m for m in b["modules"] if m not in a["modules"]]
        gone = [m for m in a["modules"] if m not in b["modules"]]
        if added:
            lines.append(f"  ~ {h}: + modules {', '.join(added)}")
        if gone:
            lines.append(f"  ~ {h}: - modules {', '.join(gone)} (stops being applied; "
                         f"what it configured stays until `./lab rebuild {{lab}} {h}`)")
        for k in ("instance_type", "disk_gb"):
            if a[k] != b[k]:
                lines.append(f"  ~ {h}: {k} {a[k]} -> {b[k]}")
        for k in ("windows_version", "windows_edition", "spot"):
            if k in a and a.get(k) != b.get(k):
                lines.append(f"  ~ {h}: {k} {a.get(k)} -> {b.get(k)} (applies on "
                             f"`./lab rebuild {{lab}} {h}`; the running host keeps its own)")
    return lines


# --------------------------------------------------------------------------
# up
# --------------------------------------------------------------------------
def _legacy_check():
    old = TERRAFORM / "terraform.tfstate"
    with contextlib.suppress(FileNotFoundError, ValueError):
        if json.loads(old.read_text()).get("resources"):
            warn(f"{old} still tracks a lab deployed with the old run.sh; it is no longer "
                 f"managed. Destroy it from a pre-upgrade checkout before it is forgotten")


def load_snapshots(ws):
    try:
        return json.loads((ws.meta / "snapshots.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


def snapshot_passwords(cfg):
    """{host: password} for Windows hosts booting from a snapshot of any local lab."""
    known = {}
    for name in all_labs():
        known.update(load_snapshots(Workspace(name)))
    out, missing = {}, []
    for h in cfg["hosts"]:
        if h["os"] == "windows" and h["ami"]:
            rec = known.get(h["ami"])
            if rec and rec.get("password"):
                out[h["name"]] = rec["password"]
            elif not h["vars"].get("ansible_password"):
                missing.append(f"{h['name']} ({h['ami']})")
    if missing:
        raise LabError(f"no recorded Administrator password for the image of {', '.join(missing)}. "
                       f"Use an AMI made by ./lab snapshot, or give the host "
                       f"vars: {{ansible_password: ...}}")
    return out


def tf_payload(ws, cfg, expires):
    """Terraform input, with the lab's availability zone chosen once and kept."""
    st = ws.state()
    zone = st.get("availability_zone")
    if zone is None:
        # A deployed lab without a recorded zone predates this: keep its zone.
        spot = [h for h in cfg["hosts"] if h["spot"]]
        zone = "" if ws.deployed() or not spot else best_spot_zone(
            cfg["lab"]["region"], [h["instance_type"] for h in spot], len(spot))
        ws.update_state(availability_zone=zone)
    data = config.tf_input(cfg, expires)
    data["lab"]["availability_zone"] = zone
    return data


def _set_phase(ws, phase):
    with contextlib.suppress(Exception):
        ws.update_state(phase=phase, phase_at=iso(utcnow()))


def deploy(ws, args, replace=()):
    """Validate, plan, (confirm,) apply, start, provision, report. Holds the lab lock."""
    with ws.lock():
        r = resolve(ws, quiet=args.quiet)
        cfg = r.cfg
        region = cfg["lab"]["region"]
        log = ws.new_log("up")
        run = Runner(log, quiet=args.quiet)
        try:
            run.say(f"[lab] {ws.name}: {len(cfg['hosts'])} host(s) in {region}, "
                    f"network {cfg['network']['vpc_cidr']} - log: {log}")
            check_aws(region)
            _legacy_check()

            st = ws.state()
            expires = expiry_for(ws, cfg, getattr(args, "extend", None))
            new_summary = config.summary(cfg)
            old_summary = st.get("applied") or {}
            removed = [{"name": h, "domain": old_summary[h]["domain"]}
                       for h in old_summary if h not in new_summary
                       and old_summary[h]["role"] == "member" and old_summary[h]["domain"]]

            atomic_write(ws.resolved_file, json.dumps(cfg, indent=2, sort_keys=True), 0o600)
            write_inventory(ws, region)

            tf = Terraform(ws, run)
            # Modules only add: a host that lost one still carries what it did.
            lost = {h: [m for m in old_summary[h]["modules"] if m not in new_summary[h]["modules"]]
                    for h in old_summary if h in new_summary and h not in replace}
            lost = {h: m for h, m in lost.items() if m}
            if lost and not args.no_infra:
                desc = "; ".join(f"{h} no longer runs {', '.join(m)}" for h, m in lost.items())
                if getattr(args, "rebuild_changed", False):
                    replace = list(replace) + list(lost)
                elif not args.yes and not args.quiet and sys.stdin.isatty() and confirm(
                        f"{desc}. Modules do not undo what they configured; rebuild "
                        f"{', '.join(lost)} from scratch now?", False):
                    replace = list(replace) + list(lost)
                else:
                    run.say(f"[lab] {desc}; its configuration stays until "
                            f"./lab rebuild {ws.name} {' '.join(lost)} (or up --rebuild-changed)")
            if not args.no_infra:
                _set_phase(ws, "terraform")
                tf_in = tf_payload(ws, cfg, expires)
                tf.write_input(tf_in)
                tf.write_secrets(snapshot_passwords(cfg))
                tf.init()
                extra = [f'-replace=aws_instance.host["{h}"]' for h in replace]
                plan = tf.plan(extra)
                diff = plan_diff(old_summary, new_summary) if old_summary else []
                run.say(f"\n{BOLD}Plan for {ws.name}{RESET}")
                for line in diff:
                    run.say(line.replace("{lab}", ws.name))
                for line in plan.lines():
                    run.say(line)
                run.say(f"  expires: {describe_expiry(expires)}\n")
                if plan.destructive:
                    lost = sorted(plan.hosts["replace"] + plan.hosts["delete"])
                    if args.quiet and not args.yes:
                        raise LabError(f"plan destroys {', '.join(lost)}; re-run with -y")
                    if not confirm(f"This destroys {', '.join(lost)} and everything on them. "
                                   f"Continue?", args.yes):
                        raise LabError("aborted, nothing changed")
                # Departing members leave the domain cleanly before they disappear.
                gone = removed + [{"name": h, "domain": new_summary[h]["domain"]}
                                  for h in replace if new_summary.get(h, {}).get("role") == "member"]
                if gone and ws.deployed():
                    _cleanup_domain(ws, run, region, gone)
                if plan.destructive and ws.deployed():
                    cancel_spot_requests(region, ws.name,
                                         plan.hosts["replace"] + plan.hosts["delete"])
                if not plan.empty:
                    _apply_with_retry(tf, run, tf_in, ws)
                ws.update_state(applied=new_summary, expires_at=expires,
                                applied_at=iso(utcnow()))
            elif not ws.deployed():
                raise LabError(f"{ws.name} is not deployed yet; run without --no-infra")

            write_host_vars(ws, cfg, tf.outputs())
            started = _start_stopped(ws, run, region, wait=True)
            if started:
                run.say(f"[lab] started stopped instance(s): {', '.join(started)}")

            if not args.no_provision:
                _set_phase(ws, "ansible")
                extra = []
                if args.limit:
                    extra += ["--limit", args.limit]
                if args.tags:
                    extra += ["--tags", args.tags]
                Ansible(ws, run, region).converge(extra, retries=args.retries)
                ws.update_state(provisioned_at=iso(utcnow()))

            outputs = tf.outputs()
            write_credentials(ws, cfg, outputs, ws.state().get("expires_at", expires))
            write_walkthrough(ws, r.notes)
            _set_phase(ws, "ready")
            if not args.quiet and ws.creds.exists():
                print("\n" + ws.creds.read_text(), flush=True)   # console only, never the log
            run.say(f"[lab] {ws.name} is ready. Credentials: {ws.creds}")
        except BaseException:
            _set_phase(ws, "failed")
            raise
        finally:
            run.close()


def _apply_with_retry(tf, run, tf_in, ws):
    try:
        tf.apply_plan()
        return
    except LabError as e:
        failure = e
    log_tail = run.log_path.read_text(errors="replace")[-20000:]
    if SPOT_CAPACITY_ERRORS.search(log_tail):
        # Not enough spot capacity (or a new account's spot quota): put the
        # hosts that are not up yet on on-demand rather than failing the lab.
        have = tf.instances_in_state()
        moved = [h["name"] for h in tf_in["hosts"] if h["spot"] and h["name"] not in have]
        for h in tf_in["hosts"]:
            if h["name"] in moved:
                h["spot"] = False
        run.say(f"\n[lab] no spot capacity for {', '.join(moved) or 'some hosts'}; "
                f"launching them on-demand instead")
        st = ws.state()
        ws.update_state(on_demand_fallback=sorted(set(st.get("on_demand_fallback", [])) | set(moved)))
        tf.write_input(tf_in)
    else:
        # Most other first-apply failures are AWS eventual consistency; a fresh
        # plan picks up whatever did get created.
        run.say(f"\n[lab] terraform apply failed ({failure}); re-planning once in 20s")
        time.sleep(20)
    tf.plan()
    tf.apply_plan()


def _cleanup_domain(ws, run, region, gone):
    run.say(f"[lab] removing {', '.join(g['name'] for g in gone)} from the domain")
    write_inventory(ws, region)
    rc = Ansible(ws, run, region).playbook(
        "cleanup.yml", "-e", json.dumps({"removed_hosts": gone}), check=False)
    if rc != 0:
        run.say("[warn] could not clean the departing computer accounts; continuing")


def _start_stopped(ws, run, region, wait):
    found = instances(region, [ws.name]).get(ws.name, [])
    stopped = [i for i in found if i["state"] in ("stopped", "stopping")]
    if not stopped:
        return []
    client = ec2(region)
    ids = [i["id"] for i in stopped]
    if any(i["state"] == "stopping" for i in stopped):
        client.get_waiter("instance_stopped").wait(InstanceIds=ids)
    client.start_instances(InstanceIds=ids)
    if wait:
        client.get_waiter("instance_running").wait(InstanceIds=ids)
    return [i["host"] for i in stopped]


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def write_credentials(ws, cfg, out, expires):
    if not out:
        return
    hosts = cfg["hosts"]
    roles = {h["role"] for h in hosts}
    mods = {m["name"] for h in hosts for m in h["modules"]}
    lines = [f"lab: {ws.name} ({cfg['lab']['region']}, {cfg['network']['vpc_cidr']})",
             f"expires: {describe_expiry(expires)}", ""]
    if roles & {"dc", "child_dc"}:
        lines += [f"domain admin          : {cfg['lab']['domain_admin']} / {out['domain_admin_password']}",
                  f"lab users (LabUser1-10): {out['lab_user_password']}",
                  f"dsrm password         : {out['dsrm_password']}"]
    if "child_dc" in roles:
        lines.append(f"child dc password     : {out['child_dc_password']}")
    if "trust" in mods:
        lines.append(f"trust password        : {out['trust_password']}")
    if "sql_server" in mods:
        lines.append(f"sql password          : {out['sql_password']}")
    if "edr_server" in mods:
        lines += [f"elastic password      : {out['elastic_password']}",
                  f"monitor password      : {out['monitor_password']}"]
    if any(h["os"] == "linux" for h in hosts):
        lines.append(f"ssh key               : {ws.key} (user ubuntu)")
    admins = out.get("windows_admin_passwords") or {}
    if admins:
        lines += ["", "local Administrator passwords:"]
        lines += [f"  {k}: {v or '(from snapshot AMI, not published by EC2)'}"
                  for k, v in sorted(admins.items())]
    lines.append("")
    if out.get("vpn_public_ip"):
        profiles = sorted(p.name for p in ws.vpn.glob("*.ovpn")) if ws.vpn.is_dir() else []
        lines += [f"VPN: {out['vpn_public_ip']} (fixed address). Import a profile from {ws.vpn}/:",
                  f"  {', '.join(profiles) or '(not fetched yet)'}",
                  "then use the private IPs below."]
    else:
        lines.append("Access is from this machine's public IP over WinRM, RDP and SSH.")
    if out.get("elastic_private_ip"):
        lines.append(f"kibana: https://{out['elastic_private_ip']}:5601 (user elastic)")
    lines.append("")
    for name, h in sorted((out.get("hosts") or {}).items()):
        lines.append(f"  {name:<15} {h['private_ip']:<13} {h['public_ip'] or '-':<15} "
                     f"{h['role']:<10} {','.join(h['modules'])}")
    if ws.notes.exists():
        lines += ["", f"Intended attack paths (spoilers): {ws.notes}"]
    atomic_write(ws.creds, "\n".join(lines) + "\n", 0o600)


def write_host_vars(ws, cfg, outputs):
    """Per-host Ansible vars: this run's module settings plus the host's password."""
    passwords = outputs.get("windows_admin_passwords") or {}
    hv = ws.inventory / "host_vars"
    hv.mkdir(parents=True, exist_ok=True)
    keep = set()
    for h in cfg["hosts"]:
        data = dict(h["ansible_vars"])
        if h["os"] == "windows" and passwords.get(h["name"]):
            data["ansible_password"] = passwords[h["name"]]
        atomic_write(hv / f"{h['name']}.yml", yaml.safe_dump(data, sort_keys=True, width=100), 0o600)
        keep.add(f"{h['name']}.yml")
    for p in hv.glob("*.yml"):
        if p.name not in keep:
            p.unlink()


def write_walkthrough(ws, notes):
    if not notes:
        with contextlib.suppress(FileNotFoundError):
            ws.notes.unlink()
        return
    out = [f"# {ws.name}: what the modules planted", "",
           "Generated from lab.yml on every `./lab up`. These are spoilers.", ""]
    by_host = {}
    for host, mod, msg in notes:
        by_host.setdefault(host, []).append((mod, msg))
    for host, items in by_host.items():
        out.append(f"## {host}")
        out += [f"- **{mod}**: {msg}" for mod, msg in items]
        out.append("")
    atomic_write(ws.notes, "\n".join(out), 0o600)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_new(args):
    ws = Workspace(args.lab)
    if ws.exists() and not args.force:
        raise LabError(f"{ws.lab_file} already exists (use --force to overwrite)")
    src = args.template
    path = EXAMPLES / f"{src}.yml" if not src.endswith((".yml", ".yaml")) else ROOT / src
    if not path.is_file():
        avail = ", ".join(sorted(p.stem for p in EXAMPLES.glob("*.yml")))
        raise LabError(f"no template {src!r}; available: {avail}")
    text = path.read_text()
    ws.dir.mkdir(parents=True, exist_ok=True)
    atomic_write(ws.lab_file, text)
    try:
        r = resolve(ws)
    except LabError as e:
        warn(f"the new lab does not validate yet:\n{e}")
        return
    n = r.cfg["network"]
    info(f"created {ws.lab_file} from {path.name}: {len(r.cfg['hosts'])} host(s), "
         f"network {n['vpc_cidr']}")
    info(f"edit it, then: ./lab up {ws.name}")


def cmd_validate(args):
    ws = Workspace(args.lab).require()
    r = resolve(ws)
    cfg = r.cfg
    print(f"{GREEN}{ws.name}: valid{RESET} - {len(cfg['hosts'])} host(s), "
          f"{cfg['lab']['region']}, {cfg['network']['vpc_cidr']}")
    for h in cfg["hosts"]:
        print(f"  {h['name']:<15} {h['os']:<8} {h['role']:<10} {h['domain'] or '-':<18} "
              f"{h['instance_type']:<10} {h['private_ip'] or 'auto':<12} "
              f"{', '.join(m['name'] for m in h['modules'])}")
    if args.show:
        print(yaml.safe_dump(cfg, sort_keys=False, width=100))


def cmd_plan(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        r = resolve(ws)
        cfg = r.cfg
        run = Runner(ws.new_log("plan"), quiet=True)
        try:
            check_aws(cfg["lab"]["region"])
            tf = Terraform(ws, run)
            expires = expiry_for(ws, cfg)
            atomic_write(ws.resolved_file, json.dumps(cfg, indent=2, sort_keys=True), 0o600)
            tf.write_input(tf_payload(ws, cfg, expires))
            tf.write_secrets(snapshot_passwords(cfg))
            tf.init()
            plan = tf.plan()
        finally:
            run.close()
    old = ws.state().get("applied") or {}
    print(f"{BOLD}Plan for {ws.name}{RESET}")
    for line in plan_diff(old, config.summary(cfg)) if old else []:
        print(line.replace("{lab}", ws.name))
    for line in plan.lines():
        print(line)
    print(f"  expires: {describe_expiry(expires)}")


def cmd_up(args):
    if len(args.labs) == 1:
        ws = Workspace(args.labs[0]).require()
        deploy(ws, args)
        return
    # Several labs: one child process each, in parallel, each with its own log.
    for name in args.labs:
        Workspace(name).require()
    passthrough = [a for a in sys.argv[2:] if a not in args.labs]
    procs = {}
    for name in args.labs:
        procs[name] = subprocess.Popen(
            [sys.executable, "-m", "labctl.cli", "up", name, "--quiet", *passthrough],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        info(f"{name}: started (log in {LABS / name / 'logs'})")
    last = {}
    while any(p.poll() is None for p in procs.values()):
        time.sleep(5)
        for name in procs:
            phase = Workspace(name).state().get("phase")
            if phase and phase != last.get(name):
                info(f"{name}: {phase}")
                last[name] = phase
    failed = []
    for name, p in procs.items():
        out = p.stdout.read().strip()
        if p.returncode == 0:
            info(f"{GREEN}{name}: ready{RESET}  (./lab creds {name})")
        else:
            failed.append(name)
            print(f"{RED}[lab] {name}: failed{RESET}\n{out}")
    if failed:
        raise LabError(f"{len(failed)} of {len(procs)} labs failed: {', '.join(failed)}")


def cmd_down(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        tf_json = ws.meta / "tf.json"
        if ws.deployed():
            if not args.yes:
                if not sys.stdin.isatty():
                    raise LabError("refusing to destroy without a terminal; pass -y")
                typed = input(f"Destroy every resource of lab {ws.name!r}? Type its name: ")
                if typed.strip() != ws.name:
                    raise LabError("aborted, nothing destroyed")
            run = Runner(ws.new_log("down"))
            try:
                check_aws(config.load_yaml(ws.lab_file).get("lab", {}).get("region")
                          or config.default_region() or "eu-west-3")
                tf = Terraform(ws, run)
                if not tf_json.exists():
                    r = resolve(ws, quiet=True)
                    tf.write_input(tf_payload(ws, r.cfg, "never"))
                tf.init()
                region = json.loads(tf_json.read_text())["lab"]["region"]
                cancelled = cancel_spot_requests(region, ws.name)
                if cancelled:
                    run.say(f"[lab] cancelled {len(cancelled)} spot request(s)")
                tf.plan(destroy=True)
                _apply_with_retry_destroy(tf, run)
            finally:
                run.close()
        else:
            info(f"{ws.name} has no deployed resources")
        for p in (ws.inventory, ws.vpn, ws.tf_data):
            shutil.rmtree(p, ignore_errors=True)
        for p in (ws.creds, ws.key, ws.notes, tf_json, ws.resolved_file, ws.meta / "plan.out",
                  ws.meta / "expire.zip"):
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        st = ws.state()
        for k in ("applied", "applied_at", "provisioned_at", "expires_at", "phase", "phase_at"):
            st.pop(k, None)
        ws.save_state(st)
    if args.purge:
        shutil.rmtree(ws.dir)
        info(f"{ws.name} destroyed and its workspace removed")
    else:
        info(f"{ws.name} destroyed; its definition stays in {ws.lab_file}")


def _apply_with_retry_destroy(tf, run):
    try:
        tf.apply_plan()
    except LabError as e:
        run.say(f"[lab] destroy failed ({e}); retrying once in 20s")
        time.sleep(20)
        tf.plan(destroy=True)
        tf.apply_plan()


def cmd_list(args):
    labs = all_labs()
    if not labs:
        print("no labs yet: ./lab new <name>")
    by_region = {}
    rows = []
    for name in labs:
        ws = Workspace(name)
        st = ws.state()
        try:
            region = (config.load_yaml(ws.lab_file).get("lab") or {}).get("region") \
                or config.default_region() or "eu-west-3"
        except ValueError:
            region = "?"
        by_region.setdefault(region, []).append(name)
        rows.append((name, region, st))
    live = {}
    if not args.offline:
        for region, names in by_region.items():
            if region == "?":
                continue
            try:
                live.update(instances(region, names))
            except Exception as e:  # noqa: BLE001
                warn(f"cannot query {region}: {e}")
    print(f"{'LAB':<20} {'REGION':<12} {'NETWORK':<15} {'HOSTS':<14} {'EXPIRES':<22} PHASE")
    for name, region, st in rows:
        net = f"10.{st['network_index']}.0.0/16" if "network_index" in st else "-"
        inst = live.get(name, [])
        running = sum(1 for i in inst if i["state"] == "running")
        hosts = f"{running}/{len(inst)} up" if inst else ("not deployed" if not Workspace(name).deployed() else "0 found")
        exp = st.get("expires_at", "-")
        if exp not in ("-", "never") and parse_iso(exp) < utcnow():
            exp = f"{exp} (past)"
        print(f"{name:<20} {region:<12} {net:<15} {hosts:<14} {exp:<22} {st.get('phase', '-')}")
    if not args.offline:
        for region in by_region or [config.default_region() or "eu-west-3"]:
            if region == "?":
                continue
            with contextlib.suppress(Exception):
                for orphan in untracked_labs(region, set(labs)):
                    warn(f"instances tagged Lab={orphan} in {region} belong to no local lab")


def cmd_status(args):
    ws = Workspace(args.lab).require()
    st = ws.state()
    r = resolve(ws, quiet=True)
    region = r.cfg["lab"]["region"]
    live = {i["host"]: i for i in instances(region, [ws.name]).get(ws.name, [])}
    applied = st.get("applied") or {}
    print(f"{BOLD}{ws.name}{RESET}  {region}  {r.cfg['network']['vpc_cidr']}  "
          f"phase={st.get('phase', '-')}")
    if st.get("expires_at"):
        print(f"expires: {describe_expiry(st['expires_at'])}")
    print(f"\n{'HOST':<15} {'STATE':<10} {'PRIVATE':<13} {'PUBLIC':<15} {'TYPE':<10} MODULES")
    for h in r.cfg["hosts"]:
        i = live.get(h["name"])
        state = i["state"] if i else ("missing" if h["name"] in applied else "not deployed")
        print(f"{h['name']:<15} {state:<10} {(i or {}).get('private_ip', '') or '-':<13} "
              f"{(i or {}).get('public_ip', '') or '-':<15} {h['instance_type']:<10} "
              f"{', '.join(m['name'] for m in h['modules'])}")
    for name in sorted(set(live) - {h["name"] for h in r.cfg["hosts"]}):
        print(f"{name:<15} {live[name]['state']:<10} {'(removed from lab.yml; ./lab up applies it)'}")
    diff = plan_diff(applied, config.summary(r.cfg)) if applied else []
    if diff:
        print(f"\n{YELLOW}lab.yml differs from what is deployed:{RESET}")
        for line in diff:
            print(line.replace("{lab}", ws.name))
        print(f"apply with: ./lab up {ws.name}")


def cmd_creds(args):
    ws = Workspace(args.lab).require()
    if not ws.creds.exists():
        raise LabError(f"{ws.name} has no credentials yet; deploy it with ./lab up {ws.name}")
    print(ws.creds.read_text(), end="")


def _lab_instances(ws):
    r = resolve(ws, quiet=True)
    region = r.cfg["lab"]["region"]
    return region, instances(region, [ws.name]).get(ws.name, [])


def cmd_stop(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        region, found = _lab_instances(ws)
        ids = [i["id"] for i in found if i["state"] in ("running", "pending")]
        if not ids:
            info(f"no running instances in {ws.name}")
            return
        ec2(region).stop_instances(InstanceIds=ids)
        info(f"stopping {len(ids)} instance(s); EBS and the VPN address keep their cost, "
             f"compute does not. Resume with ./lab start {ws.name}")


def cmd_start(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        exp = ws.state().get("expires_at")
        if exp and exp != "never" and parse_iso(exp) <= utcnow() and not args.force:
            raise LabError(f"{ws.name} expired at {exp}; the expiry Lambda would stop or "
                           f"terminate it again within the hour. Extend first: "
                           f"./lab expire {ws.name} 8h")
        region, found = _lab_instances(ws)
        if not any(i["state"] in ("stopped", "stopping") for i in found):
            info(f"nothing to start in {ws.name}")
            return
        run = Runner(ws.new_log("start"), quiet=True)
        try:
            write_host_vars(ws, cfg, tf.outputs())
            started = _start_stopped(ws, run, region, wait=True)
        finally:
            run.close()
        info(f"started {', '.join(started)}. The VPN endpoint has a fixed address, so "
             f"profiles still work; public IPs of other hosts changed.")


def cmd_expire(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        tf_json = ws.meta / "tf.json"
        if not ws.deployed() or not tf_json.exists():
            raise LabError(f"{ws.name} is not deployed; set lab.expires in lab.yml instead")
        if args.duration == "never":
            when = "never"
        else:
            problems = []
            hours = config.parse_hours(args.duration, "duration", problems)
            if problems:
                raise LabError(problems[0])
            when = iso(utcnow() + dt.timedelta(hours=hours))
        # Re-apply the last applied definition with only the expiry changed, so
        # pending lab.yml edits are not deployed as a side effect.
        data = json.loads(tf_json.read_text())
        data["lab"]["expires_at"] = when
        run = Runner(ws.new_log("expire"), quiet=True)
        try:
            tf = Terraform(ws, run)
            tf.write_input(data)
            tf.init()
            plan = tf.plan()
            if plan.destructive:
                raise LabError("changing the expiry unexpectedly plans to destroy hosts; "
                               "aborting. Run ./lab plan to investigate")
            tf.apply_plan()
        finally:
            run.close()
        ws.update_state(expires_at=when)
        if ws.creds.exists():
            text = ws.creds.read_text().splitlines()
            text = [f"expires: {describe_expiry(when)}" if line.startswith("expires:") else line
                    for line in text]
            atomic_write(ws.creds, "\n".join(text) + "\n", 0o600)
    info(f"{ws.name} now expires: {describe_expiry(when)}")


def cmd_rebuild(args):
    ws = Workspace(args.lab).require()
    r = resolve(ws, quiet=True)
    hosts = {h["name"]: h for h in r.cfg["hosts"]}
    targets = []
    for name in args.hosts:
        if name not in hosts:
            raise LabError(f"no host {name!r} in {ws.name}")
        targets.append(name)
        h = hosts[name]
        if h["role"] in ("dc", "child_dc"):
            # A new controller is a new domain: its members must rejoin it.
            deps = [o["name"] for o in r.cfg["hosts"] if o["name"] != name and o["domain"]
                    and (o["domain"] == h["domain"] or o["domain"].endswith("." + h["domain"]))]
            if deps:
                warn(f"{name} is a domain controller; rebuilding it recreates "
                     f"{h['domain']}, so {', '.join(deps)} are rebuilt too")
                targets += [d for d in deps if d not in targets]
    deploy(ws, args, replace=targets)


def _edit_and_apply(args, mutate):
    ws = Workspace(args.lab).require()
    y, data = edit.load(ws.lab_file)
    note = mutate(data)
    text = edit.dump(y, data)
    # Validate the edited file before it replaces the current one.
    resolve(ws, raw=yaml.safe_load(text))
    atomic_write(ws.lab_file, text)
    if note:
        info(note)
    info(f"updated {ws.lab_file}")
    if args.no_apply:
        info(f"apply with: ./lab up {ws.name}")
        return
    try:
        deploy(ws, args)
    except LabError as e:
        raise LabError(f"{e}\n(lab.yml keeps the edit; apply it later with ./lab up {ws.name})") from None


def _parse_kv(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise LabError(f"setting {p!r} must be key=value (value in YAML, e.g. rdp=[Helpdesk])")
        k, v = p.split("=", 1)
        out[k.strip()] = yaml.safe_load(v) if v.strip() else None
    return out


def cmd_host_add(args):
    spec = {}
    for k in ("role", "os", "domain", "type", "ip", "count", "version", "edition"):
        v = getattr(args, k)
        if v is not None:
            spec[k] = v
    if args.module:
        spec["modules"] = list(args.module)
    _edit_and_apply(args, lambda d: edit.add_host(d, args.host, spec))


def cmd_host_rm(args):
    _edit_and_apply(args, lambda d: edit.remove_host(d, args.host))


def cmd_module_add(args):
    if not config.known_module(args.module):
        raise LabError(f"no module {args.module!r}; available: {', '.join(config.all_modules())}")
    mv = _parse_kv(args.settings)
    _edit_and_apply(args, lambda d: edit.add_module(d, args.host, args.module, mv))


def cmd_module_rm(args):
    _edit_and_apply(args, lambda d: edit.remove_module(d, args.host, args.module))


def cmd_build(args):
    from .builder import run_builder
    ws, outcome = run_builder(args.lab)
    if outcome == "deploy" and ws is not None:
        deploy(ws, args)
    elif ws is not None and ws.exists():
        info(f"deploy it with: ./lab up {ws.name}")


def cmd_modules(args):
    print(f"{'MODULE':<12} {'OS':<8} {'RUNS ON':<22} DESCRIPTION")
    for m in config.all_modules():
        meta = config.meta(m)
        readme = config.MODULES_DIR / m / "README.md"
        desc = ""
        if readme.exists():
            lines = [ln.strip() for ln in readme.read_text().splitlines()[1:] if ln.strip()]
            desc = lines[0] if lines else ""
        role = meta.get("requires_role", "any")
        role = "/".join(role) if isinstance(role, list) else role
        print(f"{m:<12} {meta.get('os', 'any'):<8} {role:<22} {desc[:70]}")


def cmd_snapshot(args):
    ws = Workspace(args.lab).require()
    with ws.lock():
        region, found = _lab_instances(ws)
        if not found:
            info(f"no instances in {ws.name}")
            return
        client = ec2(region)
        stamp = utcnow().strftime("%Y%m%d%H%M")
        run = Runner(ws.new_log("snapshot"), quiet=True)
        try:
            passwords = Terraform(ws, run).outputs().get("windows_admin_passwords") or {}
        finally:
            run.close()
        recorded = load_snapshots(ws)
        for i in found:
            ami = client.create_image(InstanceId=i["id"], Name=f"{ws.name}-{i['host']}-{stamp}",
                                      NoReboot=True)["ImageId"]
            client.create_tags(Resources=[ami], Tags=[{"Key": "Lab", "Value": ws.name},
                                                      {"Key": "LabHost", "Value": i["host"]}])
            # The Administrator password inside the image: EC2 will not publish it.
            recorded[ami] = {"host": i["host"], "password": passwords.get(i["host"], ""),
                             "created_at": iso(utcnow())}
            atomic_write(ws.meta / "snapshots.json", json.dumps(recorded, indent=2), 0o600)
            print(f"{i['host']}: {ami}")
        print("\nSet 'ami: <id>' on a host to rebuild from its snapshot; ./lab remembers the "
              "Windows Administrator password each image carries.")


def cmd_sessions(args):
    ws = Workspace(args.lab).require()
    r = resolve(ws, quiet=True)
    run = Runner(ws.new_log("sessions"))
    try:
        Ansible(ws, run, r.cfg["lab"]["region"]).playbook("sessions.yml")
    finally:
        run.close()


def cmd_logs(args):
    ws = Workspace(args.lab).require()
    logs = sorted(ws.logs.glob("*.log")) if ws.logs.is_dir() else []
    if not logs:
        raise LabError(f"no logs for {ws.name} yet")
    if args.list:
        for p in logs:
            print(p)
        return
    os.execvp("tail", ["tail", "-n", str(args.lines)] + (["-f"] if args.follow else []) + [str(logs[-1])])


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------
def _deploy_flags(p, multi=False):
    p.add_argument("-y", "--yes", action="store_true", help="do not ask before destroying hosts")
    p.add_argument("--no-infra", action="store_true", help="skip Terraform, provision only")
    p.add_argument("--no-provision", action="store_true", help="skip Ansible, infrastructure only")
    p.add_argument("--limit", help="Ansible --limit (hosts or groups, e.g. srv01,mod_shares)")
    p.add_argument("--tags", help="Ansible --tags (e.g. modules)")
    p.add_argument("--retries", type=int, default=1, help="re-runs of a failed provisioning (default 1)")
    p.add_argument("--rebuild-changed", action="store_true",
                   help="rebuild hosts whose modules were removed, so nothing of them remains")
    p.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)


def _duration(v):
    if v == "never":
        return v
    problems = []
    hours = config.parse_hours(v, "duration", problems)
    if problems:
        raise argparse.ArgumentTypeError(problems[0])
    return hours


def build_parser():
    ap = argparse.ArgumentParser(
        prog="lab", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Deploy, update and tear down Active Directory labs on AWS.",
        epilog="""examples:
  ./lab                                interactive builder (same as ./lab build)
  ./lab new corp                       start from examples/starter.yml
  ./lab up corp                        deploy, or apply edits to lab.yml
  ./lab up corp red blue               several labs in parallel
  ./lab host add corp ws01 -m session  add a workstation (and deploy it)
  ./lab module add corp srv01 logon rdp=[Helpdesk]
  ./lab expire corp 48h                push the expiry back
  ./lab down corp""")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")


    p = sub.add_parser("new", help="create a lab from a template")
    p.add_argument("lab")
    p.add_argument("--from", dest="template", default="starter",
                   help="example name (examples/<name>.yml) or a path; default starter")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("list", help="every local lab, with live instance counts")
    p.add_argument("--offline", action="store_true", help="do not query AWS")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("validate", help="check lab.yml and show what it expands to")
    p.add_argument("lab")
    p.add_argument("--show", action="store_true", help="print the full expanded definition")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("plan", help="show what `up` would change, without changing it")
    p.add_argument("lab")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("up", help="deploy a lab, or bring it in line with lab.yml")
    p.add_argument("labs", nargs="+", metavar="lab")
    p.add_argument("--extend", type=_duration,
                   help="reset the expiry to now + this (8h, 2d) or 'never'")
    _deploy_flags(p, multi=True)
    p.set_defaults(fn=cmd_up)

    p = sub.add_parser("down", help="destroy a lab")
    p.add_argument("lab")
    p.add_argument("-y", "--yes", action="store_true")
    p.add_argument("--purge", action="store_true", help="also delete labs/<lab>/ and lab.yml")
    p.set_defaults(fn=cmd_down)

    p = sub.add_parser("status", help="hosts, their state, and undeployed edits")
    p.add_argument("lab")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("creds", help="print the lab's credentials")
    p.add_argument("lab")
    p.set_defaults(fn=cmd_creds)

    for name, fn, hlp in (("stop", cmd_stop, "stop every instance (keeps disks)"),
                          ("start", cmd_start, "start a stopped lab")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("lab")
        if name == "start":
            p.add_argument("--force", action="store_true", help="start even if expired")
        p.set_defaults(fn=fn)

    p = sub.add_parser("expire", help="set the expiry: 8h, 2d, 1w from now, or never")
    p.add_argument("lab")
    p.add_argument("duration")
    p.set_defaults(fn=cmd_expire)

    p = sub.add_parser("rebuild", help="recreate hosts from scratch (undoes removed modules)")
    p.add_argument("lab")
    p.add_argument("hosts", nargs="+")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_rebuild)

    host = sub.add_parser("host", help="add or remove a host").add_subparsers(
        dest="sub", required=True, metavar="action")
    p = host.add_parser("add", help="add a host to lab.yml and deploy it")
    p.add_argument("lab")
    p.add_argument("host")
    p.add_argument("--role", choices=["dc", "child_dc", "member", "standalone"])
    p.add_argument("--os", choices=["windows", "linux"])
    p.add_argument("--domain")
    p.add_argument("--type", help="instance type (default: sized from its modules)")
    p.add_argument("--ip", type=int, help="host number in the lab subnet, e.g. 20")
    p.add_argument("--count", type=int, help="stamp out <host>01..<host>NN")
    p.add_argument("--version", choices=["2016", "2019", "2022", "2025"])
    p.add_argument("--edition", choices=["full", "core"])
    p.add_argument("-m", "--module", action="append", help="module to run (repeatable)")
    p.add_argument("--no-apply", action="store_true", help="only edit lab.yml")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_host_add)
    p = host.add_parser("rm", help="remove a host from lab.yml and destroy it")
    p.add_argument("lab")
    p.add_argument("host")
    p.add_argument("--no-apply", action="store_true")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_host_rm)

    mod = sub.add_parser("module", help="add or remove a module on a host").add_subparsers(
        dest="sub", required=True, metavar="action")
    p = mod.add_parser("add", help="add a module (key=value settings) and apply it")
    p.add_argument("lab")
    p.add_argument("host")
    p.add_argument("module")
    p.add_argument("settings", nargs="*", help="key=value, value in YAML (rdp=[Helpdesk])")
    p.add_argument("--no-apply", action="store_true")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_module_add)
    p = mod.add_parser("rm", help="stop applying a module to a host")
    p.add_argument("lab")
    p.add_argument("host")
    p.add_argument("module")
    p.add_argument("--no-apply", action="store_true")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_module_rm)

    p = sub.add_parser("build", help="build or edit a lab interactively (also: ./lab alone)")
    p.add_argument("lab", nargs="?")
    _deploy_flags(p)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("modules", help="list the available modules")
    p.set_defaults(fn=cmd_modules)

    p = sub.add_parser("snapshot", help="one AMI per host")
    p.add_argument("lab")
    p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("sessions", help="who is logged on to each Windows host")
    p.add_argument("lab")
    p.set_defaults(fn=cmd_sessions)

    p = sub.add_parser("logs", help="show the latest run log")
    p.add_argument("lab")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", "--lines", type=int, default=80)
    p.add_argument("--list", action="store_true", help="list every log file")
    p.set_defaults(fn=cmd_logs)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv and sys.stdin.isatty():
        argv = ["build"]
    args = build_parser().parse_args(argv)
    for flag in ("no_infra", "no_provision", "limit", "tags", "quiet", "yes"):
        if not hasattr(args, flag):
            setattr(args, flag, False if flag not in ("limit", "tags") else None)
    if not hasattr(args, "retries"):
        args.retries = 1
    try:
        args.fn(args)
    except LabError as e:
        print(f"{RED}error:{RESET} {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\ninterrupted; re-run the same command to resume - every step is idempotent",
              file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
