#!/usr/bin/env bash
# One AMI per lab instance. Set `ami: <id>` on a host to rebuild from it.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"
eval "$(python3 "$HERE/scripts/labenv.py" "$HERE/$LAB_FILE")"

STAMP="$(date +%Y%m%d%H%M)"
FOUND=0

# JMESPath, not shell: the backticks belong to the query.
# shellcheck disable=SC2016
QUERY='Reservations[].Instances[].[InstanceId,Tags[?Key==`LabHost`]|[0].Value]'

while read -r id host; do
  [ -n "$id" ] || continue
  FOUND=1
  ami="$(aws ec2 create-image --region "$AWS_REGION" --instance-id "$id" \
    --name "$LAB_NAME-$host-$STAMP" --no-reboot --query ImageId --output text)"
  aws ec2 create-tags --region "$AWS_REGION" --resources "$ami" \
    --tags "Key=Lab,Value=$LAB_NAME" "Key=LabHost,Value=$host"
  echo "$host: $ami"
done < <(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters "Name=tag:Lab,Values=$LAB_NAME" "Name=instance-state-name,Values=running,stopped" \
  --query "$QUERY" --output text)

if [ "$FOUND" -eq 0 ]; then
  echo "no instances for $LAB_NAME"
  exit 0
fi

cat <<EOF

Set 'ami: <id>' on a host in $LAB_FILE to rebuild from a snapshot. Windows
hosts restored this way keep the Administrator password from the snapshot:
EC2 only publishes password data for a sysprepped image.
EOF
