#!/usr/bin/env bash
# Validate, build, apply the modules, write the credential summary.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"
CREDS="$HERE/lab_credentials.txt"

FORCE=0
if [ "${1:-}" = "--force" ] || [ "${SKIP_PREFLIGHT:-0}" = "1" ]; then
  FORCE=1
fi

for bin in terraform ansible-playbook jq python3; do
  command -v "$bin" >/dev/null || { echo "missing dependency: $bin" >&2; exit 1; }
done

[ -f "$HERE/$LAB_FILE" ] || { echo "no such lab file: $HERE/$LAB_FILE" >&2; exit 1; }

if [ "$FORCE" = "0" ]; then
  python3 "$HERE/scripts/preflight.py" "$HERE/$LAB_FILE"
fi

cd "$HERE/terraform"
terraform init -input=false
terraform apply -auto-approve -input=false -var "lab_file=../$LAB_FILE"

LAB_NAME="$(terraform output -raw lab_name)"
AWS_REGION="$(terraform output -raw region)"
export LAB_NAME AWS_REGION

ELASTIC_PRIV="$(terraform output -raw elastic_private_ip)"
VPN_PUB="$(terraform output -raw vpn_public_ip)"

cd "$HERE/ansible"
ansible-playbook site.yml

# Created first so the secrets never exist under the default umask.
cd "$HERE/terraform"
install -m 600 /dev/null "$CREDS"
{
  echo "lab: $LAB_NAME ($AWS_REGION)"
  echo "expires: $(terraform output -raw expires_at)"
  echo
  echo "domain admin password : $(terraform output -raw domain_admin_password)"
  echo "dsrm password         : $(terraform output -raw dsrm_password)"
  echo "lab user password     : $(terraform output -raw lab_user_password)"
  echo "elastic password      : $(terraform output -raw elastic_password)"
  echo "monitor password      : $(terraform output -raw monitor_password)"
  echo "sql password          : $(terraform output -raw sql_password)"
  echo "ssh key               : $(terraform output -raw ssh_private_key_path)"
  echo
  echo "local Administrator passwords:"
  terraform output -json windows_admin_passwords |
    jq -r 'to_entries[] | "  \(.key): \(if .value == "" then "(from snapshot AMI, not published by EC2)" else .value end)"'
  echo
  echo "Access is over the VPN. Import ansible/client1.ovpn, then use the internal IPs below."
  if [ -n "$VPN_PUB" ]; then echo "vpn endpoint: $VPN_PUB"; fi
  if [ -n "$ELASTIC_PRIV" ]; then echo "kibana: https://$ELASTIC_PRIV:5601 (user: elastic)"; fi
  echo
  terraform output -json hosts |
    jq -r 'to_entries[] | "  \(.key): \(.value.private_ip) role=\(.value.role) modules=\(.value.modules|join(","))"'
} | tee "$CREDS"
