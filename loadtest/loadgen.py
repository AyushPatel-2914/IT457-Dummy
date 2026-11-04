"""Closed-loop load generator for Mini-Netflix. Standard library only.

Each virtual user (VU) loops: pick a request from the mix, send it, record the result, think.
Every request is written to a CSV, so availability, latency and recovery time can be
computed afterwards with loadtest/analyze.py.

Examples:
    python loadtest/loadgen.py --url http://localhost:8080 --vus 20 --duration 600 --out results/s0/steady/requests.csv
    python loadtest/loadgen.py --url http://<alb-dns> --vus 5 --ramp-to 100 --duration 600 --out ...
"""
import argparse
import csv
import http.client
import json
import queue
import random
import threading
import time
import urllib.parse

# (weight, name, method, path-template). "home" is the steady-state request.
MIX = [
    (60, "home", "GET", "/?user=user{u}"),
    (25, "movie", "GET", "/movies/{m}"),
    (10, "recs", "GET", "/recommendations/user{u}"),
    (5, "login", "POST", "/login"),
]
FIELDS = ["ts_start", "ts_end", "vu", "name", "status", "latency_ms", "served_by", "recs_source", "error"]


def pick(rng):
    r = rng.uniform(0, sum(w for w, *_ in MIX))
    for w, name, method, path in MIX:
        r -= w
        if r <= 0:
            break
    u, m = rng.randint(1, 100), rng.randint(1, 1000)
    body = json.dumps({"username": f"user{u}", "password": "password"}) if method == "POST" else None
    return name, method, path.format(u=u, m=m), body


class VU(threading.Thread):
    def __init__(self, idx, args, target, out_q, stop_at, stop, active_fn):
        super().__init__(daemon=True)
        self.idx, self.args, self.target, self.out_q = idx, args, target, out_q
        self.stop_at, self.stop, self.active_fn = stop_at, stop, active_fn
        self.rng = random.Random(args.seed * 1000 + idx)
        self.conn = None

    def _conn(self):
        if self.conn is None:
            cls = http.client.HTTPSConnection if self.target.scheme == "https" else http.client.HTTPConnection
            self.conn = cls(self.target.hostname, self.target.port, timeout=self.args.timeout)
        return self.conn

    def run(self):
        while time.time() < self.stop_at and not self.stop.is_set():
            if self.idx >= self.active_fn():
                time.sleep(0.2)
                continue
            name, method, path, body = pick(self.rng)
            headers = {"Content-Type": "application/json"} if body else {}
            t0 = time.time()
            status, served_by, recs_source, error = 0, "", "", ""
            try:
                conn = self._conn()
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                resp.read()
                status, served_by = resp.status, resp.getheader("X-Served-By", "")
                recs_source = resp.getheader("X-Recs-Source", "")
                if resp.getheader("Connection", "").lower() == "close":
                    self.conn.close()
                    self.conn = None
            except Exception as exc:  # connection refused, reset, timeout...
                error = f"{type(exc).__name__}: {exc}"[:200]
                if self.conn is not None:
                    self.conn.close()
                self.conn = None
            t1 = time.time()
            self.out_q.put([f"{t0:.3f}", f"{t1:.3f}", self.idx, name, status, f"{(t1 - t0) * 1000:.1f}", served_by, recs_source, error])
            if error:
                time.sleep(0.1)  # avoid a hot loop while the target is down
            time.sleep(self.rng.expovariate(1 / self.args.think) if self.args.think > 0 else 0)


def writer(path, out_q, done):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        while not (done.is_set() and out_q.empty()):
            try:
                w.writerow(out_q.get(timeout=0.5))
            except queue.Empty:
                f.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--vus", type=int, default=20, help="virtual users (start value if --ramp-to is set)")
    ap.add_argument("--ramp-to", type=int, help="linearly ramp VUs to this value over the run")
    ap.add_argument("--duration", type=float, default=600, help="seconds")
    ap.add_argument("--think", type=float, default=0.2, help="mean think time between requests, seconds")
    ap.add_argument("--timeout", type=float, default=2.0, help="per-request timeout, seconds")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    target = urllib.parse.urlparse(args.url if "://" in args.url else f"http://{args.url}")
    start = time.time()
    stop_at = start + args.duration
    max_vus = max(args.vus, args.ramp_to or 0)

    def active():
        if not args.ramp_to:
            return args.vus
        frac = min((time.time() - start) / args.duration, 1)
        return round(args.vus + (args.ramp_to - args.vus) * frac)

    out_q, done, stop = queue.Queue(), threading.Event(), threading.Event()
    wt = threading.Thread(target=writer, args=(args.out, out_q, done))
    wt.start()
    vus = [VU(i, args, target, out_q, stop_at, stop, active) for i in range(max_vus)]
    for v in vus:
        v.start()
    print(f"loadgen: {args.url} vus={args.vus}{'->' + str(args.ramp_to) if args.ramp_to else ''} "
          f"duration={args.duration:.0f}s -> {args.out}", flush=True)
    try:
        while time.time() < stop_at:
            time.sleep(min(10, max(stop_at - time.time(), 0)))
            print(f"  t={time.time() - start:5.0f}s active_vus={active()} queued={out_q.qsize()}", flush=True)
    except KeyboardInterrupt:
        print("loadgen: interrupted, flushing results", flush=True)
        stop.set()
    for v in vus:
        v.join(timeout=args.timeout + 1)
    done.set()
    wt.join()


if __name__ == "__main__":
    main()
