#!/usr/bin/env python3
"""Print shell exports for the lab name and region, for `eval` in the scripts."""
import shlex
import sys

import yaml


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: labenv.py <lab.yml>")

    with open(sys.argv[1], encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    lab = cfg.get("lab") or {}
    for key in ("name", "region"):
        if not lab.get(key):
            sys.exit(f"{sys.argv[1]}: lab.{key} is missing")

    print(f"export LAB_NAME={shlex.quote(str(lab['name']))}")
    print(f"export AWS_REGION={shlex.quote(str(lab['region']))}")


if __name__ == "__main__":
    main()
