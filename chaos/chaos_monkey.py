"""Mini Chaos Monkey: terminate (or stop) random Mini-Netflix EC2 instances on a schedule.

Safety rails (Week 2 plan, Section 7.4):
  * only instances tagged project=<project> AND stage=<stage> are candidates;
  * refuses to act if more than --max-instances match (guards against a wrong filter);
  * --dry-run logs what it would do without touching anything.

Every action is appended to an events CSV so kill times can be marked on the charts.

Examples:
    python chaos/chaos_monkey.py --stage s2 --duration 600 --interval 120 180 --events results/s2/e1-run1/events.csv
    python chaos/chaos_monkey.py --stage s2 --az us-east-1a --once --events ...      # E2: lose an AZ
    python chaos/chaos_monkey.py --stage s1 --action stop --once --events ...        # E1 on S1 (restart by hand)
"""
import argparse
import csv
import os
import random
import sys
import time

import boto3

EVENT_FIELDS = ["ts", "action", "target", "az", "stage", "dry_run", "note"]


def log_event(path, **row):
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"ts": f"{time.time():.3f}", **row})
    print(f"[{time.strftime('%H:%M:%S')}] {row}", flush=True)


def candidates(ec2, project, stage, az=None):
    filters = [
        {"Name": "tag:project", "Values": [project]},
        {"Name": "tag:stage", "Values": [stage]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ]
    if az:
        filters.append({"Name": "availability-zone", "Values": [az]})
    found = []
    for page in ec2.get_paginator("describe_instances").paginate(Filters=filters):
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                found.append((inst["InstanceId"], inst["Placement"]["AvailabilityZone"]))
    return found


def act(ec2, ids, action, dry_run):
    if dry_run:
        return
    if action == "terminate":
        ec2.terminate_instances(InstanceIds=ids)
    else:
        ec2.stop_instances(InstanceIds=ids)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--project", default="mini-netflix")
    ap.add_argument("--stage", required=True, choices=["s1", "s2"])
    ap.add_argument("--action", default="terminate", choices=["terminate", "stop"])
    ap.add_argument("--az", help="kill every matching instance in this AZ, once (experiment E2)")
    ap.add_argument("--duration", type=float, default=600, help="seconds to keep running")
    ap.add_argument("--interval", type=float, nargs=2, default=[120, 180], metavar=("MIN", "MAX"),
                    help="random wait between kills, seconds")
    ap.add_argument("--initial-delay", type=float, default=60, help="steady-state period before the first kill")
    ap.add_argument("--once", action="store_true", help="one kill, then exit")
    ap.add_argument("--max-instances", type=int, default=4)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--events", required=True, help="events CSV to append to")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    ec2 = boto3.client("ec2", region_name=args.region)
    end = time.time() + args.duration
    print(f"chaos_monkey: stage={args.stage} action={args.action} az={args.az} dry_run={args.dry_run}", flush=True)
    time.sleep(args.initial_delay)

    while time.time() < end:
        all_targets = candidates(ec2, args.project, args.stage)
        if len(all_targets) > args.max_instances:
            sys.exit(f"refusing: {len(all_targets)} instances match the filter (max {args.max_instances})")
        if args.az:
            victims = [t for t in all_targets if t[1] == args.az]
        else:
            victims = [rng.choice(all_targets)] if all_targets else []
        if not victims:
            log_event(args.events, action="none", target="", az=args.az or "", stage=args.stage,
                      dry_run=args.dry_run, note="no running instance matched")
        else:
            act(ec2, [v[0] for v in victims], args.action, args.dry_run)
            for iid, az in victims:
                log_event(args.events, action=args.action if not args.az else f"az-{args.action}", target=iid,
                          az=az, stage=args.stage, dry_run=args.dry_run, note="")
        if args.once or args.az:
            break
        time.sleep(min(rng.uniform(*args.interval), max(end - time.time(), 0)))


if __name__ == "__main__":
    main()
