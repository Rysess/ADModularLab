#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
read -p "Destroy the lab? (yes) " c
[ "$c" = "yes" ] || exit 0
cd "$HERE/terraform"
terraform destroy -auto-approve
rm -f "$HERE/ansible/inventory.yml" "$HERE/ansible/client1.ovpn" lab-key.pem
