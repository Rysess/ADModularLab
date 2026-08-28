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
terraform apply -auto-approve -input=false \
  -var "lab_file=../$LAB_FILE" -var "deploy_stamp=$(date -u +%s)"

LAB_NAME="$(terraform output -raw lab_name)"
AWS_REGION="$(terraform output -raw region)"
export LAB_NAME AWS_REGION

ELASTIC_PRIV="$(terraform output -raw elastic_private_ip)"
VPN_PUB="$(terraform output -raw vpn_public_ip)"

cd "$HERE/ansible"
ansible-playbook site.yml

# Only the credentials the lab actually uses.
cd "$HERE/terraform"
HOSTS_JSON="$(terraform output -json hosts)"
has() { echo "$HOSTS_JSON" | jq -e "$1" >/dev/null; }
has_role() { has "any(.[]; .role == \"$1\")"; }
has_module() { has "any(.[]; .modules | index(\"$1\"))"; }
has_os() { has "any(.[]; .os == \"$1\")"; }

# Created first so the secrets never exist under the default umask.
install -m 600 /dev/null "$CREDS"
{
  echo "lab: $LAB_NAME ($AWS_REGION)"
  echo "expires: $(terraform output -raw expires_at)"
  echo
  if has_role dc || has_role child_dc; then
    echo "domain admin password : $(terraform output -raw domain_admin_password)"
    echo "dsrm password         : $(terraform output -raw dsrm_password)"
    echo "lab user password     : $(terraform output -raw lab_user_password)"
  fi
  has_role child_dc  && echo "child dc password     : $(terraform output -raw child_dc_password)"
  has_module trust   && echo "trust password        : $(terraform output -raw trust_password)"
  has_module sql_server && echo "sql password          : $(terraform output -raw sql_password)"
  if has_module edr_server; then
    echo "elastic password      : $(terraform output -raw elastic_password)"
    echo "monitor password      : $(terraform output -raw monitor_password)"
  fi
  has_os linux && echo "ssh key               : $(terraform output -raw ssh_private_key_path)"
  if has_os windows; then
    echo
    echo "local Administrator passwords:"
    terraform output -json windows_admin_passwords |
      jq -r 'to_entries[] | "  \(.key): \(if .value == "" then "(from snapshot AMI, not published by EC2)" else .value end)"'
  fi
  echo
  if [ -n "$VPN_PUB" ]; then
    echo "Access is over the VPN. Import ansible/client1.ovpn, then use the internal IPs below."
    echo "vpn endpoint: $VPN_PUB"
  else
    echo "Access is from this machine's public IP over WinRM, RDP and SSH."
  fi
  if [ -n "$ELASTIC_PRIV" ]; then echo "kibana: https://$ELASTIC_PRIV:5601 (user: elastic)"; fi
  echo
  echo "$HOSTS_JSON" |
    jq -r 'to_entries[] | "  \(.key): \(.value.private_ip) role=\(.value.role) modules=\(.value.modules|join(","))"'
} | tee "$CREDS"
