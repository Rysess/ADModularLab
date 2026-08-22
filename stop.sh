#!/usr/bin/env bash
# Stop every running instance. EBS keeps its cost, compute does not.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LAB_FILE="${LAB_FILE:-lab.yml}"
eval "$(python3 "$HERE/scripts/labenv.py" "$HERE/$LAB_FILE")"

mapfile -t IDS < <(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters "Name=tag:Lab,Values=$LAB_NAME" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' '\n' | grep .)

if [ "${#IDS[@]}" -eq 0 ]; then
  echo "no running instances for $LAB_NAME"
  exit 0
fi

aws ec2 stop-instances --region "$AWS_REGION" --instance-ids "${IDS[@]}" --output table
