"""Analyse one experiment run: availability, latency, recovery time, plus a timeline chart.

Inputs live in one run folder (see results/README.md):
    requests.csv   from loadtest/loadgen.py              (required)
    events.csv     from chaos/chaos_monkey.py, fault.py  (optional; kill / fault markers)
    watch.csv      from chaos/watch.py                   (optional; instance and target health)
Outputs written to the same folder: summary.json, timeline.png

Definitions (fixed in the Week 2 plan, Section 7):
    steady state      GET / ("home") returning HTTP 200 within 1 s
    availability      successful home requests / all home requests
    degraded second   a 1 s bucket with availability < 99 %
    outage second     a 1 s bucket with availability < 50 %
    time to recover   seconds from a chaos event until availability stays >= 99 % for 10 s
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SLO = 0.99
OK_LATENCY_MS = 1000
STABLE_S = 10


def load(run):
    req = pd.read_csv(run / "requests.csv")
    t0 = req["ts_start"].min()
    req["t"] = req["ts_start"] - t0
    req["ok"] = (req["status"] == 200) & (req["latency_ms"] <= OK_LATENCY_MS)
    ev = pd.read_csv(run / "events.csv") if (run / "events.csv").exists() else pd.DataFrame(columns=["ts", "action"])
    if not ev.empty:
        ev = ev[(ev["ts"] >= t0) & (ev["ts"] <= req["ts_end"].max())].copy()
        ev["t"] = ev["ts"] - t0
    watch = pd.read_csv(run / "watch.csv") if (run / "watch.csv").exists() else None
    if watch is not None:
        watch = watch[(watch["ts"] >= t0 - 5) & (watch["ts"] <= req["ts_end"].max() + 5)].copy()
        watch["t"] = watch["ts"] - t0
    return req, ev, watch, t0


def per_second(home):
    sec = home.groupby(home["t"].astype(int))["ok"].agg(["mean", "size"])
    sec = sec.reindex(range(int(home["t"].max()) + 1))
    sec["mean"] = sec["mean"].ffill()  # an empty second keeps the previous state
    return sec


def longest_run(mask):
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def recovery_after(sec, t_event, t_limit):
    """Seconds after t_event until availability is >= SLO for STABLE_S consecutive seconds."""
    good = sec["mean"] >= SLO
    start = int(t_event)
    for s in range(start, min(int(t_limit), len(sec) - STABLE_S)):
        if good.iloc[s:s + STABLE_S].all():
            return max(s - t_event, 0.0)
    return None  # did not recover within the run


def capacity_after(watch, t_event, col):
    """Detection and restore times from watch.csv for a health column (e.g. tg_healthy)."""
    if watch is None or col not in watch or watch[col].isna().all():
        return None, None
    before = watch[watch["t"] < t_event][col].dropna()
    if before.empty:
        return None, None
    baseline = before.iloc[-1]
    after = watch[watch["t"] >= t_event]
    dropped = after[after[col] < baseline]
    if dropped.empty:
        return None, 0.0
    t_detect = dropped["t"].iloc[0]
    restored = after[(after["t"] > t_detect) & (after[col] >= baseline)]
    t_restore = restored["t"].iloc[0] - t_event if not restored.empty else None
    return t_detect - t_event, t_restore


def summarise(run, label):
    req, ev, watch, t0 = load(run)
    home = req[req["name"] == "home"]
    sec = per_second(home)
    ok_home = home[home["status"] == 200]["latency_ms"]
    duration = req["ts_end"].max() - t0
    summary = {
        "label": label or run.name,
        "run_dir": str(run),
        "duration_s": round(duration, 1),
        "requests_total": int(len(req)),
        "throughput_rps": round(len(req) / duration, 1),
        "home_requests": int(len(home)),
        "availability_pct": round(100 * home["ok"].mean(), 3),
        "slo_met": bool(home["ok"].mean() >= SLO),
        "error_rate_all_pct": round(100 * (req["status"] != 200).mean(), 3),
        "status_counts": {str(k): int(v) for k, v in req["status"].value_counts().items()},
        "home_p50_ms": round(ok_home.quantile(0.5), 1),
        "home_p95_ms": round(ok_home.quantile(0.95), 1),
        "home_p99_ms": round(ok_home.quantile(0.99), 1),
        "degraded_seconds": int((sec["mean"] < SLO).sum()),
        "outage_seconds": int((sec["mean"] < 0.5).sum()),
        "longest_outage_s": longest_run(sec["mean"] < 0.5),
        "fallback_pct_of_home": round(100 * (home["recs_source"] == "fallback").mean(), 2),
        "events": [],
    }
    health_col = "tg_healthy" if watch is not None and "tg_healthy" in watch and watch["tg_healthy"].notna().any() else "ec2_running"
    ev_times = list(ev["t"]) if not ev.empty else []
    for i, row in enumerate(ev.itertuples()):
        t_next = ev_times[i + 1] if i + 1 < len(ev_times) else sec.index[-1]
        detect, restore = capacity_after(watch, row.t, health_col)
        window = sec.loc[int(row.t):int(t_next)]
        summary["events"].append({
            "t": round(row.t, 1),
            "action": row.action,
            "target": getattr(row, "target", ""),
            "time_to_recover_s": recovery_after(sec, row.t, t_next),
            "degraded_seconds": int((window["mean"] < SLO).sum()),
            "time_to_detect_s": None if detect is None else round(detect, 1),
            "time_to_restore_capacity_s": None if restore is None else round(restore, 1),
        })
    rec = [e["time_to_recover_s"] for e in summary["events"] if e["time_to_recover_s"] is not None]
    cap = [e["time_to_restore_capacity_s"] for e in summary["events"] if e["time_to_restore_capacity_s"] is not None]
    summary["mean_time_to_recover_s"] = round(sum(rec) / len(rec), 1) if rec else None
    summary["unrecovered_events"] = sum(e["time_to_recover_s"] is None for e in summary["events"])
    summary["mean_time_to_restore_capacity_s"] = round(sum(cap) / len(cap), 1) if cap else None
    plot_timeline(run, summary["label"], req, sec, ev, watch, health_col)
    return summary


def plot_timeline(run, label, req, sec, ev, watch, health_col):
    panels = 4 if watch is not None else 3
    fig, axes = plt.subplots(panels, 1, figsize=(11, 2.3 * panels), sharex=True)
    home = req[req["name"] == "home"]
    win = 5
    avail = home.groupby((home["t"] // win) * win)["ok"].mean() * 100
    axes[0].plot(avail.index, avail.values, color="#2a6", lw=1.4)
    axes[0].axhline(SLO * 100, color="#b33", ls="--", lw=0.8, label="99% SLO")
    axes[0].set_ylabel(f"availability %\n({win}s window)")
    axes[0].set_ylim(-5, 105)
    axes[0].legend(loc="lower left", fontsize=8)

    ok = home[home["status"] == 200]
    p = ok.groupby((ok["t"] // 10) * 10)["latency_ms"].quantile([0.5, 0.95]).unstack()
    if not p.empty:
        axes[1].plot(p.index, p[0.5], label="p50", color="#36c")
        axes[1].plot(p.index, p[0.95], label="p95", color="#c80")
    axes[1].set_ylabel("home latency ms\n(10s window)")
    axes[1].legend(loc="upper left", fontsize=8)

    rps = req.groupby(req["t"].astype(int)).size().rolling(5, min_periods=1).mean()
    err = req[req["status"] != 200].groupby(req["t"].astype(int)).size().reindex(rps.index, fill_value=0)
    axes[2].plot(rps.index, rps.values, color="#555", lw=1, label="requests/s")
    axes[2].fill_between(err.index, err.values, color="#b33", alpha=0.5, label="errors/s")
    axes[2].set_ylabel("req/s")
    axes[2].legend(loc="upper left", fontsize=8)

    if watch is not None:
        for col, colour in [(health_col, "#2a6"), ("asg_inservice", "#36c"), ("asg_desired", "#999")]:
            if col in watch and watch[col].notna().any():
                axes[3].step(watch["t"], watch[col], where="post", label=col, color=colour)
        axes[3].set_ylabel("instances")
        axes[3].legend(loc="upper left", fontsize=8)

    for row in ev.itertuples() if not ev.empty else []:
        for ax in axes:
            ax.axvline(row.t, color="#b33", lw=0.8, alpha=0.7)
        axes[0].text(row.t, 102, str(row.action)[:12], fontsize=7, color="#b33", rotation=90, va="top", ha="right")
    axes[-1].set_xlabel("seconds since start")
    fig.suptitle(label, fontsize=11)
    fig.tight_layout()
    fig.savefig(run / "timeline.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--label")
    args = ap.parse_args()
    summary = summarise(args.run_dir, args.label)
    (args.run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    keys = ["label", "availability_pct", "slo_met", "home_p50_ms", "home_p95_ms", "throughput_rps",
            "longest_outage_s", "mean_time_to_recover_s", "mean_time_to_restore_capacity_s"]
    print(json.dumps({k: summary[k] for k in keys}, indent=2))


if __name__ == "__main__":
    main()
