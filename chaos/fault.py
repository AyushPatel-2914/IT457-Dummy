"""Service-level faults for experiments E3 (latency) and E4 (recommendations down).

Local mode talks to the docker-compose.services.yml stack; --ssm mode runs the same action on
every running S2 instance through AWS Systems Manager.

Examples (local):
    python chaos/fault.py latency --ms 300 --events results/local/e3/events.csv
    python chaos/fault.py recs-down --events ...
    python chaos/fault.py clear --events ...
Examples (AWS S2):
    python chaos/fault.py latency --ms 300 --ssm --events ...
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from chaos_monkey import log_event  # noqa: E402

COMPOSE = ["docker", "compose", "-f", os.path.join(os.path.dirname(__file__), "..", "app", "docker-compose.services.yml")]

SHELL = {
    "latency": "curl -s -XPOST localhost:5002/admin/fault -H 'Content-Type: application/json' -d '{body}'",
    "clear": "curl -s -XDELETE localhost:5002/admin/fault; docker start recommendations",
    "recs-down": "docker stop recommendations",
    "recs-up": "docker start recommendations",
}


def run_local(action, ms, url):
    if action == "latency":
        req = urllib.request.Request(f"{url}/admin/fault", data=json.dumps({"latency_ms": ms}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    elif action == "clear":
        subprocess.run(COMPOSE + ["start", "recommendations"], check=True)
        time.sleep(1)
        urllib.request.urlopen(urllib.request.Request(f"{url}/admin/fault", method="DELETE"), timeout=5).read()
    elif action == "recs-down":
        subprocess.run(COMPOSE + ["stop", "-t", "1", "recommendations"], check=True)
    elif action == "recs-up":
        subprocess.run(COMPOSE + ["start", "recommendations"], check=True)


def run_ssm(action, ms, region, project):
    import boto3
    ec2 = boto3.client("ec2", region_name=region)
    ssm = boto3.client("ssm", region_name=region)
    res = ec2.describe_instances(Filters=[{"Name": "tag:project", "Values": [project]},
                                          {"Name": "tag:stage", "Values": ["s2"]},
                                          {"Name": "instance-state-name", "Values": ["running"]}])
    ids = [i["InstanceId"] for r in res["Reservations"] for i in r["Instances"]]
    if not ids:
        sys.exit("no running s2 instances")
    cmd = SHELL[action].format(body=json.dumps({"latency_ms": ms}))
    ssm.send_command(InstanceIds=ids, DocumentName="AWS-RunShellScript", Parameters={"commands": [cmd]})
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=list(SHELL))
    ap.add_argument("--ms", type=int, default=300)
    ap.add_argument("--url", default="http://localhost:5002", help="recommendations service (local mode)")
    ap.add_argument("--ssm", action="store_true")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--project", default="mini-netflix")
    ap.add_argument("--delay", type=float, default=0, help="wait before acting (steady-state period)")
    ap.add_argument("--events", required=True)
    args = ap.parse_args()

    time.sleep(args.delay)
    if args.ssm:
        targets = ",".join(run_ssm(args.action, args.ms, args.region, args.project))
    else:
        run_local(args.action, args.ms, args.url)
        targets = "local"
    note = f"latency_ms={args.ms}" if args.action == "latency" else ""
    log_event(args.events, action=args.action, target=targets, az="", stage="s2", dry_run=False, note=note)


if __name__ == "__main__":
    main()
