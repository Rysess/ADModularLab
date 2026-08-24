"""Stop or terminate lab instances whose ExpiresAt tag has passed."""
import datetime as dt
import os

import boto3

LAB = os.environ["LAB_NAME"]
ACTION = os.environ.get("EXPIRE_ACTION", "stop")


def expired_instances(ec2, now):
    states = ["running"] if ACTION == "stop" else ["running", "stopped"]
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[
            {"Name": "tag:Lab", "Values": [LAB]},
            {"Name": "instance-state-name", "Values": states},
        ]
    )
    for page in pages:
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                stamp = tags.get("ExpiresAt")
                if not stamp:
                    continue
                try:
                    when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when <= now:
                    yield instance["InstanceId"]


def handler(event, context):
    ec2 = boto3.client("ec2")
    ids = sorted(set(expired_instances(ec2, dt.datetime.now(dt.timezone.utc))))

    if not ids:
        print(f"{LAB}: nothing expired")
        return {"action": ACTION, "instances": []}

    print(f"{LAB}: {ACTION} {ids}")
    if ACTION == "terminate":
        ec2.terminate_instances(InstanceIds=ids)
    else:
        ec2.stop_instances(InstanceIds=ids)
    return {"action": ACTION, "instances": ids}
