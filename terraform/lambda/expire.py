"""Stop or terminate lab instances whose ExpiresAt tag has passed."""
import datetime as dt
import os

import boto3

LAB = os.environ["LAB_NAME"]
ACTION = os.environ.get("EXPIRE_ACTION", "terminate")


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
                    continue      # "never"
                if when <= now:
                    yield instance


def handler(event, context):
    ec2 = boto3.client("ec2")
    found = list(expired_instances(ec2, dt.datetime.now(dt.timezone.utc)))
    ids = sorted({i["InstanceId"] for i in found})

    if not ids:
        print(f"{LAB}: nothing expired")
        return {"action": ACTION, "instances": []}

    print(f"{LAB}: {ACTION} {ids}")
    if ACTION == "terminate":
        # A persistent spot request relaunches a terminated instance: cancel first.
        spot = sorted({i["SpotInstanceRequestId"] for i in found if i.get("SpotInstanceRequestId")})
        if spot:
            ec2.cancel_spot_instance_requests(SpotInstanceRequestIds=spot)
        ec2.terminate_instances(InstanceIds=ids)
        # An Elastic IP outlives its instance and keeps billing; release it.
        for addr in ec2.describe_addresses(Filters=[{"Name": "tag:Lab", "Values": [LAB]}])["Addresses"]:
            try:
                if addr.get("AssociationId"):
                    ec2.disassociate_address(AssociationId=addr["AssociationId"])
                ec2.release_address(AllocationId=addr["AllocationId"])
            except Exception as e:  # noqa: BLE001 - best effort, retried next hour
                print(f"{LAB}: could not release {addr.get('PublicIp')}: {e}")
    else:
        ec2.stop_instances(InstanceIds=ids)
    return {"action": ACTION, "instances": ids}
