"""Run one experiment end to end: load + (watcher) + chaos, then analyse.

Results go to results/<stage>/<exp>[-<tag>]/run<N>/ (requests.csv, events.csv, watch.csv,
summary.json, timeline.png).

Experiments (Week 2 plan, Section 7.4):
    E0  steady load, no chaos (baseline for every stage)
    E1  kill one random instance every 2-3 min (S1: stop the single instance once)
    E2  kill every instance in one AZ
    E3  add latency to the recommendations service (run with BREAKER=on and off)
    E4  stop the recommendations service           (run with BREAKER=on and off)
    E5  ramp load 5 -> 100 VUs to force scale-out

Examples:
    python chaos/run_experiment.py --stage s0 --exp E0 --run 1 --url http://localhost:8080
    python chaos/run_experiment.py --stage local-s2 --exp E4 --tag breaker-on --run 1 --url http://localhost:8081
    python chaos/run_experiment.py --stage s2 --exp E1 --run 1 --url http://<alb-dns> \
        --asg mini-netflix-s2 --target-group mini-netflix-catalogue
    python chaos/run_experiment.py --stage s1 --exp E1 --run 1 --url http://<s1-ip> --probe-url http://<s1-ip>
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True, choices=["s0", "s1", "s2", "local-s2"])
    ap.add_argument("--exp", required=True, choices=["E0", "E1", "E2", "E3", "E4", "E5"])
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--tag", default="", help="variant label, e.g. breaker-on")
    ap.add_argument("--url", required=True)
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--vus", type=int, default=20)
    ap.add_argument("--fault-at", type=float, default=60, help="E3/E4: seconds before the fault")
    ap.add_argument("--fault-for", type=float, default=180, help="E3/E4: seconds the fault lasts")
    ap.add_argument("--latency-ms", type=int, default=300)
    ap.add_argument("--asg")
    ap.add_argument("--target-group")
    ap.add_argument("--probe-url")
    ap.add_argument("--az", help="E2: the AZ to take out")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--dry-run", action="store_true", help="chaos actions are logged but not executed")
    args = ap.parse_args()

    name = args.exp.lower() + (f"-{args.tag}" if args.tag else "")
    run_dir = ROOT / "results" / args.stage / name / f"run{args.run}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for f in ["requests.csv", "events.csv", "watch.csv", "summary.json", "timeline.png"]:
        (run_dir / f).unlink(missing_ok=True)
    events = str(run_dir / "events.csv")
    aws_stage = args.stage in ("s1", "s2")
    region = ["--region", args.region]
    procs = []

    if aws_stage:
        cmd = [PY, ROOT / "chaos/watch.py", "--stage", args.stage, "--duration", str(args.duration + 30),
               "--out", run_dir / "watch.csv", *region]
        if args.asg:
            cmd += ["--asg", args.asg]
        if args.target_group:
            cmd += ["--target-group", args.target_group]
        if args.probe_url:
            cmd += ["--probe-url", args.probe_url]
        watcher = subprocess.Popen([str(c) for c in cmd])
        time.sleep(3)
    else:
        watcher = None

    load = [PY, ROOT / "loadtest/loadgen.py", "--url", args.url, "--duration", str(args.duration),
            "--out", run_dir / "requests.csv", "--seed", str(args.run)]
    load += ["--vus", "5", "--ramp-to", "100"] if args.exp == "E5" else ["--vus", str(args.vus)]
    loadgen = subprocess.Popen([str(c) for c in load])

    dry = ["--dry-run"] if args.dry_run else []
    if args.exp == "E1":
        if not aws_stage:
            sys.exit("E1 needs AWS (s1 or s2); for local runs use E4")
        cmd = [PY, ROOT / "chaos/chaos_monkey.py", "--stage", args.stage, "--duration", str(args.duration - 60),
               "--events", events, *region, *dry]
        cmd += ["--action", "stop", "--once"] if args.stage == "s1" else ["--interval", "120", "180"]
        procs.append(subprocess.Popen([str(c) for c in cmd]))
    elif args.exp == "E2":
        if not (args.az and args.stage == "s2"):
            sys.exit("E2 needs --stage s2 and --az")
        procs.append(subprocess.Popen([str(c) for c in [PY, ROOT / "chaos/chaos_monkey.py", "--stage", "s2",
                                                         "--az", args.az, "--events", events, *region, *dry]]))
    elif args.exp in ("E3", "E4"):
        action = "latency" if args.exp == "E3" else "recs-down"
        undo = "clear" if args.exp == "E3" else "recs-up"
        ssm = ["--ssm"] if aws_stage else []
        for act, delay in [(action, args.fault_at), (undo, args.fault_at + args.fault_for)]:
            procs.append(subprocess.Popen([str(c) for c in [PY, ROOT / "chaos/fault.py", act, "--ms", args.latency_ms,
                                                             "--delay", delay, "--events", events, *ssm, *region]]))

    loadgen.wait()
    for p in procs:
        p.wait(timeout=120)
    if watcher:
        watcher.terminate()
    label = f"{args.stage.upper()} {args.exp}{' ' + args.tag if args.tag else ''} run {args.run}"
    subprocess.run([PY, str(ROOT / "loadtest/analyze.py"), str(run_dir), "--label", label], check=True)
    print(f"results in {run_dir}")


if __name__ == "__main__":
    main()
