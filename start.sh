#!/usr/bin/env bash
# Start every stopped instance in the lab.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"
eval "$(python3 "$HERE/scripts/labenv.py" "$HERE/$LAB_FILE")"

mapfile -t IDS < <(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters "Name=tag:Lab,Values=$LAB_NAME" "Name=instance-state-name,Values=stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' '\n' | grep .)

if [ "${#IDS[@]}" -eq 0 ]; then
  echo "no stopped instances for $LAB_NAME"
  exit 0
fi

aws ec2 start-instances --region "$AWS_REGION" --instance-ids "${IDS[@]}" --output table
aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "${IDS[@]}"

cat <<EOF
started; public IPs have changed and the dynamic inventory will pick them up.

The VPN endpoint moved with them, so re-run the vpn module to refresh
ansible/client1.ovpn:

  cd $HERE/ansible && LAB_NAME=$LAB_NAME AWS_REGION=$AWS_REGION \\
    ansible-playbook site.yml --tags modules --limit mod_vpn
EOF
