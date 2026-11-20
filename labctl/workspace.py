"""Per-lab workspaces.

Every lab lives in labs/<name>/: its definition (lab.yml), its Terraform state,
its generated inventory and secrets, its logs and its VPN profiles. Nothing a
lab generates is written outside that directory, so any number of labs can be
deployed, updated and destroyed side by side from one checkout.
"""
import contextlib
import datetime as dt
import errno
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABS = ROOT / "labs"
ANSIBLE = ROOT / "ansible"
TERRAFORM = ROOT / "terraform"
EXAMPLES = ROOT / "examples"

LAB_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

# 10.<n>.0.0/16 per lab; 0-9 are left alone, they are common home/VPN ranges.
NETWORK_INDEX_MIN = 10
NETWORK_INDEX_MAX = 250


class LabError(Exception):
    """An error worth showing the user without a traceback."""


class Busy(LabError):
    pass


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def atomic_write(path, text, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(path, what):
    """Exclusive, non-blocking lock; tells the user who holds it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES):
                raise
            fh.seek(0)
            holder = fh.read().strip() or "another process"
            raise Busy(f"{what} is busy ({holder}); wait for it to finish") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid {os.getpid()}")
        fh.flush()
        yield
    finally:
        fh.close()


@contextlib.contextmanager
def global_lock(blocking=True):
    """Serialises the few operations shared by every lab (allocation, tf init)."""
    LABS.mkdir(exist_ok=True)
    with open(LABS / ".global.lock", "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Workspace:
    def __init__(self, name):
        if not LAB_NAME_RE.match(name or ""):
            raise LabError(f"lab name {name!r}: 1-31 chars, lowercase letters, digits "
                           f"and '-', starting with a letter or digit")
        self.name = name
        self.dir = LABS / name
        self.lab_file = self.dir / "lab.yml"
        self.meta = self.dir / ".lab"
        self.state_file = self.meta / "state.json"
        self.resolved_file = self.meta / "resolved.json"
        self.tf_data = self.meta / "terraform"
        self.tf_state = self.meta / "terraform.tfstate"
        self.inventory = self.dir / "inventory"
        self.logs = self.dir / "logs"
        self.vpn = self.dir / "vpn"
        self.creds = self.dir / "credentials.txt"
        self.notes = self.dir / "walkthrough.md"
        self.key = self.dir / "lab-key.pem"

    # -- existence ---------------------------------------------------------
    def exists(self):
        return self.lab_file.is_file()

    def require(self):
        if not self.exists():
            known = ", ".join(all_labs()) or "none"
            raise LabError(f"no lab named {self.name!r} (expected {self.lab_file}). "
                           f"Known labs: {known}. Create one with: ./lab new {self.name}")
        return self

    def deployed(self):
        """True once Terraform has recorded any resource for this lab."""
        try:
            data = json.loads(self.tf_state.read_text())
        except (FileNotFoundError, ValueError):
            return False
        return bool(data.get("resources"))

    # -- state -------------------------------------------------------------
    def state(self):
        try:
            return json.loads(self.state_file.read_text())
        except FileNotFoundError:
            return {}

    def save_state(self, state):
        atomic_write(self.state_file, json.dumps(state, indent=2, sort_keys=True) + "\n")

    def update_state(self, **kv):
        st = self.state()
        st.update(kv)
        self.save_state(st)
        return st

    # -- locking -------------------------------------------------------------
    def lock(self):
        return file_lock(self.meta / "lock", f"lab {self.name!r}")

    # -- logging -------------------------------------------------------------
    def new_log(self, command):
        self.logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        path = self.logs / f"{stamp}-{command}.log"
        # Keep the last 30 runs.
        old = sorted(self.logs.glob("*.log"))[:-29]
        for p in old:
            with contextlib.suppress(OSError):
                p.unlink()
        return path

    # -- network -------------------------------------------------------------
    def network_index(self, requested=None, taken=lambda: ()):
        """This lab's 10.<n>.0.0/16. Allocated once, then stable for its lifetime.

        `taken` lists indexes in use elsewhere (VPCs already in the account); it
        is only called when a new index has to be chosen.
        """
        st = self.state()
        if "network_index" in st and requested in (None, st["network_index"]):
            return st["network_index"]
        with global_lock():
            used = {n: "an existing VPC in the account" for n in (taken() if requested is None else ())}
            for other in all_labs():
                if other == self.name:
                    continue
                n = Workspace(other).state().get("network_index")
                if n is not None:
                    used[n] = other
            if requested is not None:
                if requested in used:
                    raise LabError(f"lab.network index {requested} is already used by lab "
                                   f"{used[requested]!r}; two labs on one VPN client would "
                                   f"route over each other")
                n = requested
            else:
                free = [i for i in range(NETWORK_INDEX_MIN, NETWORK_INDEX_MAX + 1) if i not in used]
                if not free:
                    raise LabError("no free lab network left")
                n = free[0]
            if self.deployed() and "network_index" in st and st["network_index"] != n:
                raise LabError(f"lab {self.name!r} is deployed on 10.{st['network_index']}.0.0/16; "
                               f"changing lab.network would rebuild every host. Destroy it first")
            self.update_state(network_index=n)
            return n


def all_labs():
    if not LABS.is_dir():
        return []
    return sorted(p.name for p in LABS.iterdir()
                  if p.is_dir() and (p / "lab.yml").is_file() and LAB_NAME_RE.match(p.name))
