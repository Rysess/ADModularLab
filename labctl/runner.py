"""Running Terraform, Ansible and AWS calls for one lab."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

from .workspace import ANSIBLE, ROOT, TERRAFORM, LabError, atomic_write, global_lock


def tool(name):
    """A venv-local binary first, then PATH."""
    local = ROOT / "venv" / "bin" / name
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise LabError(f"{name} is not installed (see README: Install)")
    return found


class Runner:
    """Streams a command to the console (unless quiet) and to the run's log."""

    def __init__(self, log_path, quiet=False):
        self.log_path = Path(log_path)
        self.quiet = quiet
        # Logs can carry hostnames, IPs and account names: owner-only.
        fd = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._log = os.fdopen(fd, "a", encoding="utf-8")

    def close(self):
        self._log.close()

    def say(self, msg=""):
        self._log.write(msg + "\n")
        self._log.flush()
        if not self.quiet:
            print(msg, flush=True)

    def run(self, cmd, cwd, env=None, check=True, capture=False, show=True):
        self._log.write(f"\n$ {' '.join(map(str, cmd))}\n")
        self._log.flush()
        full_env = {**os.environ, **(env or {})}
        # 077: Terraform state, plans and host_vars hold every lab secret.
        umask = lambda: os.umask(0o077)  # noqa: E731
        if capture:
            proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=full_env, text=True,
                                  capture_output=True, preexec_fn=umask)
            rc, out, err = proc.returncode, proc.stdout, proc.stderr
            if err:
                self._log.write(err)
            self._log.flush()
        else:
            p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd), env=full_env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                                 preexec_fn=umask)
            for line in p.stdout:
                self._log.write(line)
                if show and not self.quiet:
                    sys.stdout.write(line)
                    sys.stdout.flush()
            rc, out, err = p.wait(), "", ""
            self._log.flush()
        if check and rc != 0:
            tail = err.strip().splitlines()[-15:] if capture else []
            raise LabError(f"{Path(cmd[0]).name} {cmd[1] if len(cmd) > 1 else ''} failed "
                           f"(exit {rc}); full output in {self.log_path}"
                           + ("\n" + "\n".join(tail) if tail else ""))
        return rc, out


# --------------------------------------------------------------------------
# Terraform
# --------------------------------------------------------------------------
class Terraform:
    def __init__(self, ws, runner):
        self.ws = ws
        self.r = runner
        self.bin = tool("terraform")
        cache = Path.home() / ".terraform.d" / "plugin-cache"
        cache.mkdir(parents=True, exist_ok=True)
        self.env = {
            "TF_DATA_DIR": str(ws.tf_data),
            "TF_PLUGIN_CACHE_DIR": str(cache),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
        }
        self.tf_json = ws.meta / "tf.json"
        self.plan_file = ws.meta / "plan.out"
        self.secrets_file = ws.meta / "secrets.tfvars.json"

    def vars(self):
        out = ["-var", f"config_file={self.tf_json}", "-var", f"out_dir={self.ws.dir}"]
        if self.secrets_file.exists():
            out += ["-var-file", str(self.secrets_file)]
        return out

    def write_secrets(self, known_admin_passwords):
        """Sensitive inputs go in a 0600 var-file, never on a command line."""
        atomic_write(self.secrets_file,
                     json.dumps({"known_admin_passwords": known_admin_passwords}), 0o600)

    def write_input(self, data):
        atomic_write(self.tf_json, json.dumps(data, indent=2, sort_keys=True), 0o600)

    def init(self):
        # Shared provider cache and lock file: one init at a time across labs.
        with global_lock():
            self.r.run([self.bin, "init", "-input=false", "-reconfigure", "-no-color",
                        f"-backend-config=path={self.ws.tf_state}"],
                       TERRAFORM, self.env, show=False)
        self.migrate()

    def migrate(self):
        """One-off state moves for labs created by earlier versions."""
        if not self.ws.deployed():
            return
        _, listing = self.r.run([self.bin, "state", "list"], TERRAFORM, self.env,
                                capture=True, check=False)
        have = set(listing.split())
        # The internet route used to be inline in the route table; adopt it.
        if "aws_route_table.lab" in have and "aws_route.internet" not in have:
            _, rtb = self.r.run([self.bin, "state", "show", "-no-color", "aws_route_table.lab"],
                                TERRAFORM, self.env, capture=True)
            rid = next(line.split("=")[1].strip().strip('"') for line in rtb.splitlines()
                       if line.strip().startswith("id "))
            self.r.run([self.bin, "import", "-input=false", "-no-color", *self.vars(),
                        "aws_route.internet", f"{rid}_0.0.0.0/0"], TERRAFORM, self.env, show=False)

    def plan(self, extra=(), destroy=False):
        args = [self.bin, "plan", "-input=false", "-no-color", "-out", str(self.plan_file),
                *self.vars(), *extra]
        if destroy:
            args.append("-destroy")
        self.r.run(args, TERRAFORM, self.env, show=False)
        _, js = self.r.run([self.bin, "show", "-json", str(self.plan_file)],
                           TERRAFORM, self.env, capture=True)
        return PlanSummary(json.loads(js))

    def apply_plan(self):
        self.r.run([self.bin, "apply", "-input=false", "-no-color", "-auto-approve",
                    str(self.plan_file)], TERRAFORM, self.env)

    def instances_in_state(self):
        _, listing = self.r.run([self.bin, "state", "list"], TERRAFORM, self.env,
                                capture=True, check=False)
        return {m.group(1) for m in re.finditer(r'aws_instance\.host\["([^"]+)"\]', listing)}

    def outputs(self):
        if not self.ws.deployed():
            return {}
        rc, js = self.r.run([self.bin, "output", "-json", "-no-color"], TERRAFORM, self.env,
                            capture=True, check=False)
        if rc != 0:
            return {}
        return {k: v["value"] for k, v in json.loads(js or "{}").items()}


class PlanSummary:
    def __init__(self, plan):
        self.hosts = {"create": [], "update": [], "replace": [], "delete": []}
        self.other = {"create": 0, "update": 0, "replace": 0, "delete": 0}
        for rc in plan.get("resource_changes", []):
            actions = rc["change"]["actions"]
            if actions in (["no-op"], ["read"]):
                continue
            kind = ("replace" if "delete" in actions and "create" in actions
                    else actions[0] if actions[0] in self.other else None)
            if kind is None:
                continue
            if rc["type"] == "aws_instance":
                self.hosts[kind].append(rc.get("index", rc["address"]))
            else:
                self.other[kind] += 1

    @property
    def destructive(self):
        return bool(self.hosts["replace"] or self.hosts["delete"])

    @property
    def empty(self):
        return not any(self.hosts.values()) and not any(self.other.values())

    def lines(self):
        sym = {"create": "+", "update": "~", "replace": "±", "delete": "-"}
        verb = {"create": "create", "update": "update in place", "replace": "REBUILD",
                "delete": "DESTROY"}
        out = []
        for k in ("create", "update", "replace", "delete"):
            if self.hosts[k]:
                out.append(f"  {sym[k]} {verb[k]}: {', '.join(sorted(self.hosts[k]))}")
        rest = [f"{n} to {k}" for k, n in self.other.items() if n]
        if rest:
            out.append(f"  · other resources: {', '.join(rest)}")
        return out or ["  no infrastructure changes"]


# --------------------------------------------------------------------------
# Ansible
# --------------------------------------------------------------------------
def write_inventory(ws, region):
    inv = {
        "plugin": "amazon.aws.aws_ec2",
        "regions": [region],
        "filters": {"tag:Lab": ws.name, "instance-state-name": "running"},
        "hostnames": ["tag:LabHost"],
        "keyed_groups": [
            {"key": "tags.Os", "prefix": "", "separator": ""},
            {"key": "tags.LabRole", "prefix": "role"},
            {"key": "tags.Modules.split(',') | select() | list", "prefix": "mod"},
        ],
        "compose": {
            "ansible_host": "public_ip_address",
            "private_ip": "private_ip_address",
            "modules": "tags.Modules.split(',') | select() | list",
        },
    }
    ws.inventory.mkdir(parents=True, exist_ok=True)
    atomic_write(ws.inventory / "aws_ec2.yml",
                 "# Generated by ./lab; regenerated on every run.\n"
                 + yaml.safe_dump(inv, sort_keys=False))


class Ansible:
    def __init__(self, ws, runner, region):
        self.ws = ws
        self.r = runner
        self.bin = tool("ansible-playbook")
        self.env = {
            "ANSIBLE_CONFIG": str(ANSIBLE / "ansible.cfg"),
            "AWS_REGION": region,
            "PYTHONUNBUFFERED": "1",   # stream to the log as it happens
            "ANSIBLE_NOCOLOR": "1" if runner.quiet or not sys.stdout.isatty() else "0",
            "ANSIBLE_FORCE_COLOR": "0" if runner.quiet or not sys.stdout.isatty() else "1",
        }

    def playbook(self, name, *extra, check=True):
        return self.r.run([self.bin, "-i", str(self.ws.inventory), name, *extra],
                          ANSIBLE, self.env, check=check)[0]

    def converge(self, extra=(), retries=1):
        """site.yml, re-run on failure: every role is idempotent, and most
        failures in a fresh lab are a Windows host still settling."""
        for attempt in range(retries + 1):
            if attempt:
                self.r.say(f"\n[lab] provisioning failed; retrying ({attempt}/{retries}) in 30s")
                time.sleep(30)
            # Fresh barrier markers: a stale "ready" would let hosts run ahead.
            run_dir = self.ws.meta / "run"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir(parents=True, mode=0o700)
            self.env["LAB_RUN_DIR"] = str(run_dir)
            if self.playbook("site.yml", *extra, check=False) == 0:
                return
        raise LabError(f"provisioning failed after {retries + 1} attempt(s); see "
                       f"{self.r.log_path}. Fix the cause and re-run: ./lab up {self.ws.name}")


# --------------------------------------------------------------------------
# AWS
# --------------------------------------------------------------------------
def ec2(region):
    import boto3
    return boto3.client("ec2", region_name=region)


def instances(region, lab_names):
    """{lab: [{id, host, state, public_ip, private_ip, type}]} for the given labs."""
    out = {n: [] for n in lab_names}
    if not lab_names:
        return out
    pages = ec2(region).get_paginator("describe_instances").paginate(Filters=[
        {"Name": "tag:Lab", "Values": list(lab_names)},
        {"Name": "instance-state-name",
         "Values": ["pending", "running", "stopping", "stopped"]},
    ])
    for page in pages:
        for res in page["Reservations"]:
            for i in res["Instances"]:
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                out.setdefault(tags.get("Lab"), []).append({
                    "id": i["InstanceId"], "host": tags.get("LabHost", "?"),
                    "state": i["State"]["Name"], "type": i["InstanceType"],
                    "public_ip": i.get("PublicIpAddress", ""),
                    "private_ip": i.get("PrivateIpAddress", ""),
                })
    return out


def untracked_labs(region, known):
    """Lab tags with live instances in `region` that no local workspace knows."""
    found = set()
    pages = ec2(region).get_paginator("describe_instances").paginate(Filters=[
        {"Name": "tag:ManagedBy", "Values": ["adlab"]},
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
    ])
    for page in pages:
        for res in page["Reservations"]:
            for i in res["Instances"]:
                tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])}
                if tags.get("Lab") and tags["Lab"] not in known:
                    found.add(tags["Lab"])
    return sorted(found)


SPOT_CAPACITY_ERRORS = re.compile(
    r"InsufficientInstanceCapacity|MaxSpotInstanceCountExceeded|SpotMaxPriceTooLow|"
    r"InsufficientCapacity|UnfulfillableCapacity|capacity-not-available|"
    r"There is no Spot capacity", re.I)


def cancel_spot_requests(region, lab, hosts=None):
    """Cancel the persistent spot requests behind a lab's instances.

    Terminating a persistent-request instance re-opens the request, which then
    launches a replacement nobody tracks. Cancelling leaves the instance alone.
    """
    client = ec2(region)
    filters = [{"Name": "tag:Lab", "Values": [lab]},
               {"Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"]}]
    if hosts:
        filters.append({"Name": "tag:LabHost", "Values": list(hosts)})
    ids = []
    for page in client.get_paginator("describe_instances").paginate(Filters=filters):
        for res in page["Reservations"]:
            ids += [i["SpotInstanceRequestId"] for i in res["Instances"]
                    if i.get("SpotInstanceRequestId")]
    if ids:
        client.cancel_spot_instance_requests(SpotInstanceRequestIds=ids)
    return ids


def best_spot_zone(region, instance_types, count):
    """The availability zone AWS scores best for these spot instances, or ''."""
    try:
        client = ec2(region)
        scores = client.get_spot_placement_scores(
            InstanceTypes=sorted(set(instance_types)), TargetCapacity=max(count, 1),
            SingleAvailabilityZone=True, RegionNames=[region])["SpotPlacementScores"]
        names = {z["ZoneId"]: z["ZoneName"] for z in
                 client.describe_availability_zones()["AvailabilityZones"]
                 if z["State"] == "available"}
        ranked = sorted((-s["Score"], names[s["AvailabilityZoneId"]]) for s in scores
                        if s.get("AvailabilityZoneId") in names)
        return ranked[0][1] if ranked else ""
    except Exception:  # noqa: BLE001 - no score just means the default zone
        return ""


def used_network_indexes(region):
    """10.<n>.0.0/16 blocks already taken by VPCs in the account (any checkout)."""
    import re as _re
    out = set()
    try:
        for v in ec2(region).describe_vpcs()["Vpcs"]:
            for assoc in v.get("CidrBlockAssociationSet", []):
                m = _re.fullmatch(r"10\.(\d+)\.\d+\.\d+/\d+", assoc["CidrBlock"])
                if m:
                    out.add(int(m.group(1)))
    except Exception:  # noqa: BLE001 - offline: fall back to local knowledge
        pass
    return out


def check_aws(region):
    import boto3
    import botocore.exceptions
    try:
        ident = boto3.client("sts", region_name=region).get_caller_identity()
    except botocore.exceptions.NoCredentialsError:
        raise LabError("no AWS credentials: run `aws configure` (or set AWS_PROFILE)") from None
    except botocore.exceptions.ClientError as e:
        raise LabError(f"AWS rejected the credentials: {e}") from None
    return ident["Arn"]
