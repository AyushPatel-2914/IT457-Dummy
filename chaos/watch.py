"""Poll AWS every few seconds and record instance / target health to a CSV.

Columns: ts, asg_desired, asg_inservice, tg_healthy, tg_unhealthy, ec2_running, probe_ok
  * asg_*       from the Auto Scaling Group (S2)
  * tg_*        healthy targets in the ALB target group (S2; the catalogue group is the one that matters)
  * ec2_running running instances tagged project/stage (S1 and S2)
  * probe_ok    1 if GET <probe-url>/health answered 200 within 1 s (S1: is the single server up?)

Examples:
    python chaos/watch.py --stage s2 --asg mini-netflix-s2 --target-group mini-netflix-catalogue --out .../watch.csv
    python chaos/watch.py --stage s1 --probe-url http://<s1-ip> --out .../watch.csv
"""
import argparse
import csv
import os
import time
import urllib.request

import boto3

FIELDS = ["ts", "asg_desired", "asg_inservice", "tg_healthy", "tg_unhealthy", "ec2_running", "probe_ok"]


def probe(url):
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=1) as r:
            return int(r.status == 200)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--project", default="mini-netflix")
    ap.add_argument("--stage", required=True)
    ap.add_argument("--asg")
    ap.add_argument("--target-group", help="target group name")
    ap.add_argument("--probe-url")
    ap.add_argument("--interval", type=float, default=2)
    ap.add_argument("--duration", type=float, default=900)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ec2 = boto3.client("ec2", region_name=args.region)
    asg = boto3.client("autoscaling", region_name=args.region) if args.asg else None
    elb = boto3.client("elbv2", region_name=args.region) if args.target_group else None
    tg_arn = elb.describe_target_groups(Names=[args.target_group])["TargetGroups"][0]["TargetGroupArn"] if elb else None

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    end = time.time() + args.duration
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        while time.time() < end:
            row = {"ts": f"{time.time():.3f}"}
            try:
                if asg:
                    g = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[args.asg])["AutoScalingGroups"][0]
                    row["asg_desired"] = g["DesiredCapacity"]
                    row["asg_inservice"] = sum(i["LifecycleState"] == "InService" for i in g["Instances"])
                if elb:
                    states = [t["TargetHealth"]["State"] for t in
                              elb.describe_target_health(TargetGroupArn=tg_arn)["TargetHealthDescriptions"]]
                    row["tg_healthy"] = states.count("healthy")
                    row["tg_unhealthy"] = len(states) - states.count("healthy")
                res = ec2.describe_instances(Filters=[
                    {"Name": "tag:project", "Values": [args.project]},
                    {"Name": "tag:stage", "Values": [args.stage]},
                    {"Name": "instance-state-name", "Values": ["running"]}])
                row["ec2_running"] = sum(len(r["Instances"]) for r in res["Reservations"])
            except Exception as exc:
                print(f"watch: API error {exc}", flush=True)
            if args.probe_url:
                row["probe_ok"] = probe(args.probe_url)
            w.writerow(row)
            f.flush()
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
