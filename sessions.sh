#!/usr/bin/env bash
# Show who has an interactive or RDP session open on each Windows host.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"
eval "$(python3 "$HERE/scripts/labenv.py" "$HERE/$LAB_FILE")"

cd "$HERE/ansible"
exec ansible-playbook sessions.yml
