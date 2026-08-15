#!/usr/bin/env bash
# Destroy the lab and remove every generated artifact.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"

read -r -p "Destroy the lab defined by $LAB_FILE? (yes) " confirm
[ "$confirm" = "yes" ] || exit 0

cd "$HERE/terraform"
terraform destroy -auto-approve -var "lab_file=../$LAB_FILE"

rm -f "$HERE/terraform/lab-key.pem" \
      "$HERE/ansible/inventory.yml" \
      "$HERE/ansible/client1.ovpn" \
      "$HERE/ansible/group_vars/all/lab_secrets.yml" \
      "$HERE/ansible/group_vars/all/lab_facts.yml" \
      "$HERE/lab_credentials.txt"
rm -rf "$HERE/ansible/host_vars"
