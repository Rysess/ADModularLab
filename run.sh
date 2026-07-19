#!/bin/bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
[ "${SKIP_PREFLIGHT:-0}" = "1" ] && FORCE=1
[ "$FORCE" = "1" ] || python3 "$HERE/scripts/preflight.py"

cd "$HERE/terraform"
terraform init -input=false
terraform apply -auto-approve -input=false

ADMIN_PW=$(terraform output -raw admin_password)
ELASTIC_PRIV=$(terraform output -raw elastic_private_ip)
VPN_PUB=$(terraform output -json hosts | jq -r 'to_entries[] | select(.value.modules|index("vpn")) | .value.public_ip' | head -n1)

cd "$HERE/ansible"
sleep 60
ansible-playbook site.yml

cd "$HERE/terraform"
{
  echo "admin password: $ADMIN_PW"
  echo "ssh key:        $(terraform output -raw ssh_private_key_path)"
  echo
  echo "Access is over the VPN. Import ansible/client1.ovpn, then use the internal IPs below."
  [ -n "$VPN_PUB" ] && echo "vpn endpoint: $VPN_PUB"
  [ -n "$ELASTIC_PRIV" ] && echo "kibana: https://$ELASTIC_PRIV:5601 (user: elastic)"
  echo
  terraform output -json hosts | jq -r 'to_entries[] | "  \(.key): \(.value.private_ip)  role=\(.value.role)  modules=\(.value.modules|join(","))"'
} | tee "$HERE/lab_credentials.txt"
chmod 600 "$HERE/lab_credentials.txt"
