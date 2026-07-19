#!/usr/bin/env python3
"""Validate lab.yml against each role's lab_meta.yml (os + min_instance_type)."""
import os, sys, yaml

MEM = {
    "t3.nano": 0.5, "t3.micro": 1, "t3.small": 2, "t3.medium": 4,
    "t3.large": 8, "t3.xlarge": 16, "t3.2xlarge": 32,
    "t3a.nano": 0.5, "t3a.micro": 1, "t3a.small": 2, "t3a.medium": 4,
    "t3a.large": 8, "t3a.xlarge": 16, "t3a.2xlarge": 32,
    "t2.nano": 0.5, "t2.micro": 1, "t2.small": 2, "t2.medium": 4,
    "t2.large": 8, "t2.xlarge": 16,
    "m5.large": 8, "m5.xlarge": 16, "m5.2xlarge": 32,
    "m6i.large": 8, "m6i.xlarge": 16, "c5.large": 4, "c5.xlarge": 8,
}
ROLE_DIR = {"dc": "dc", "member": "domain_member", "standalone": None}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
ROLE_DIRS = [os.path.join(ROOT, "ansible", "roles"),
             os.path.join(ROOT, "ansible", "modules")]

def meta(role):
    for d in ROLE_DIRS:
        p = os.path.join(d, role, "lab_meta.yml")
        if os.path.isfile(p):
            return yaml.safe_load(open(p)) or {}
    return {}

def main():
    lab = yaml.safe_load(open(os.path.join(ROOT, "lab.yml")))
    defaults = lab.get("defaults", {})
    problems, warns = [], []

    for h in lab["hosts"]:
        os_ = h["os"]
        itype = h.get("instance_type") or defaults.get(f"{os_}_instance_type")
        roles = []
        rd = ROLE_DIR.get(h.get("role"))
        if rd:
            roles.append(rd)
        roles += h.get("modules", [])

        for r in roles:
            m = meta(r)
            req_os = m.get("os", "any")
            if req_os != "any" and req_os != os_:
                problems.append(f"{h['name']}: role '{r}' requires os={req_os}, host is {os_}")
            mint = m.get("min_instance_type")
            if mint:
                hr, mr = MEM.get(itype), MEM.get(mint)
                if hr is None:
                    warns.append(f"{h['name']}: unknown instance_type '{itype}', "
                                 f"cannot verify '{r}' needs >= {mint}")
                elif mr is not None and hr < mr:
                    problems.append(f"{h['name']}: role '{r}' needs >= {mint}, "
                                    f"host is {itype}")

    for w in warns:
        print(f"[warn] {w}")
    if problems:
        print("\nPreflight FAILED:")
        for p in problems:
            print(f"  - {p}")
        print("\nFix lab.yml, or bypass with:  ./deploy.sh --force   (or SKIP_PREFLIGHT=1)")
        sys.exit(1)
    print("[preflight] OK — every host satisfies its roles' os/size requirements")

if __name__ == "__main__":
    main()
