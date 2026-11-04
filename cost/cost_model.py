"""S5 cost model. Every number here is an ESTIMATE (list prices from memory of the public pricing
pages, us-east-1 / us-east1, on-demand, no free tier). Check each PRICES entry against the AWS and
GCP pricing calculators before submission and update PRICES_CHECKED.

Two parts:
  A. What our own experiment stages cost per hour and per 1,000 requests (uses measured throughput
     from results/<stage>/e0/run*/summary.json where available).
  B. A Netflix-like workload priced on AWS, GCP and on-premises across scales, split like Netflix's
     own system: B1 control plane (variable vs steady demand) and B2 video delivery (cloud CDN vs an
     own CDN in the Open Connect style), to find where each option becomes cheaper.

Outputs: cost/cost_table.md, results/charts/cost_breakeven.png
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HOURS_PER_MONTH = 730
PRICES_CHECKED = "not yet checked against the calculators (values from memory)"

# ------------------------------------------------------------------ list prices (USD)
PRICES = {
    "aws": {
        "t3.micro_h": 0.0104,
        "public_ipv4_h": 0.005,
        "ebs_gp3_gb_month": 0.08,
        "ec2_detailed_monitoring_month": 2.10,
        "alb_h": 0.0225,
        "alb_lcu_h": 0.008,
        "rds_db.t3.micro_h": 0.017,
        "rds_gp2_gb_month": 0.115,
        "vcpu_h": 0.048,            # general purpose (m6i.large = $0.096 for 2 vCPU)
        "commit_discount": 0.30,    # ~1-year Compute Savings Plan
        "storage_gb_month": 0.023,  # S3 Standard
        "egress_tiers_gb": [(10_240, 0.09), (51_200, 0.085), (153_600, 0.07), (float("inf"), 0.05)],
    },
    "gcp": {
        "vcpu_h": 0.0486,           # n2-standard-2 = $0.0971 for 2 vCPU
        "commit_discount": 0.37,    # 1-year committed use discount
        "storage_gb_month": 0.020,  # Cloud Storage Standard
        "egress_tiers_gb": [(1_024, 0.12), (10_240, 0.11), (float("inf"), 0.08)],  # premium tier
    },
    "onprem": {
        "server_capex": 25_000,     # 2 x 32-core (128 vCPU), 512 GB RAM
        "server_vcpus": 128,
        "server_life_months": 60,
        "server_power_kw": 0.6,
        "pue": 1.5,
        "kwh": 0.12,
        "colo_per_server_month": 150,
        "storage_tb_month": 8,      # 3x replicated HDD incl. chassis and power, amortised
        "transit_per_mbps_month": 0.50,   # 95th-percentile billed IP transit at volume
        "transit_min_month": 500,         # minimum commit (e.g. 1 Gbps port)
        "staff_fte_month": 10_000,        # loaded cost of one engineer
        "servers_per_fte": 40,
        "min_fte": 1.0,
        "headroom": 1.3,                  # N+1 / growth headroom on top of peak
    },
}
CLOUD_HEADROOM = 1.3  # autoscaling target ~70% utilisation

CDN_TIERS = {  # per GB delivered
    "aws": [(10_240, 0.085), (51_200, 0.080), (153_600, 0.060), (512_000, 0.040),
            (1_048_576, 0.030), (5_242_880, 0.025), (float("inf"), 0.020)],   # CloudFront, North America
    "gcp": [(10_240, 0.08), (153_600, 0.055), (float("inf"), 0.03)],          # Cloud CDN
}
OWN_CDN = {"appliance_capex": 15_000, "appliance_life_months": 48, "appliance_gbps": 20,
           "appliance_colo_month": 300, "paid_transit_share": 0.3, "appliances_per_fte": 100}


def tiered(gb, tiers):
    cost, prev = 0.0, 0.0
    for limit, price in tiers:
        band = min(gb, limit) - prev
        if band <= 0:
            break
        cost += band * price
        prev = limit
    return cost


def total(c):
    return sum(c.values())


def staff(fte):
    return fte * PRICES["onprem"]["staff_fte_month"]


# ------------------------------------------------------------------ part A: our stages
def stage_hourly():
    a = PRICES["aws"]
    ebs_h = 8 * a["ebs_gp3_gb_month"] / HOURS_PER_MONTH
    s1 = a["t3.micro_h"] + a["public_ipv4_h"] + ebs_h
    per_instance = s1 + a["ec2_detailed_monitoring_month"] / HOURS_PER_MONTH
    s2_fixed = (a["alb_h"] + a["alb_lcu_h"] + 2 * a["public_ipv4_h"]  # ALB has one public IP per AZ
                + a["rds_db.t3.micro_h"] + 20 * a["rds_gp2_gb_month"] / HOURS_PER_MONTH)
    return {
        "S0 (laptop Docker)": ("s0", 0.0, "no cloud cost; hardware already owned"),
        "S1 (1 x t3.micro)": ("s1", s1, "EC2 + public IPv4 + 8 GB EBS"),
        "S2 (2 instances)": ("s2", s2_fixed + 2 * per_instance, "ALB + RDS + 2 x (EC2, IPv4, EBS, detailed monitoring)"),
        "S2 (4 instances, max)": (None, s2_fixed + 4 * per_instance, "fully scaled out"),
    }


def measured_throughput():
    """Steady-load (E0) throughput per stage from summary.json files, if they exist."""
    out = {}
    for f in ROOT.glob("results/*/e0/run*/summary.json"):
        out.setdefault(f.parts[-4], []).append(json.loads(f.read_text())["throughput_rps"])
    return {k: sum(v) / len(v) for k, v in out.items()}


# ------------------------------------------------------------------ part B: Netflix-like workload
# Netflix split its system in two, and so do we:
#   control plane  - APIs, recommendations, billing: compute-heavy, demand varies, little egress
#   video delivery - the bytes of the films: huge, steady, almost all egress (Open Connect)

def control_cloud(provider, vcpu, peak_ratio):
    p = PRICES[provider]
    # Pay for average demand plus headroom. The always-on floor (roughly avg / peak_ratio) is
    # bought on a commitment at a discount; the rest is on-demand.
    baseline = vcpu / peak_ratio
    burst = max(vcpu * CLOUD_HEADROOM - baseline, 0)
    compute = (baseline * (1 - p["commit_discount"]) + burst) * p["vcpu_h"] * HOURS_PER_MONTH
    storage = vcpu * 0.05 * 1024 * p["storage_gb_month"]
    egress = tiered(vcpu * 0.05 * 1024, p["egress_tiers_gb"])
    # Managed infrastructure: assume a quarter of the on-prem operations effort per server.
    servers = vcpu * CLOUD_HEADROOM / PRICES["onprem"]["server_vcpus"]
    fte = max(0.25, servers / (PRICES["onprem"]["servers_per_fte"] * 4))
    return {"compute": compute, "storage": storage, "egress": egress, "staff": staff(fte)}


def control_onprem(vcpu, peak_ratio):
    p = PRICES["onprem"]
    servers = max(int(np.ceil(vcpu * peak_ratio * p["headroom"] / p["server_vcpus"])), 2)  # own the peak
    per_server = (p["server_capex"] / p["server_life_months"]
                  + p["server_power_kw"] * p["pue"] * HOURS_PER_MONTH * p["kwh"]
                  + p["colo_per_server_month"])
    mbps = vcpu * 0.05 * 8e6 / (HOURS_PER_MONTH * 3600)
    return {"compute": servers * per_server, "storage": vcpu * 0.05 * p["storage_tb_month"],
            "egress": max(mbps * 2 * p["transit_per_mbps_month"], p["transit_min_month"]),
            "staff": staff(max(servers / p["servers_per_fte"], p["min_fte"]))}


def delivery_cloud(provider, tb):
    return {"egress": tiered(tb * 1024, CDN_TIERS[provider])}


def delivery_own(tb):
    """Own CDN in the Open Connect style: appliances inside ISPs, most traffic settlement-free."""
    c = OWN_CDN
    avg_gbps = tb * 8_000 / (HOURS_PER_MONTH * 3600)
    peak_gbps = avg_gbps * 2  # evening peak
    n = max(int(np.ceil(peak_gbps * PRICES["onprem"]["headroom"] / c["appliance_gbps"])), 2)
    transit = max(peak_gbps * 1000 * c["paid_transit_share"] * PRICES["onprem"]["transit_per_mbps_month"],
                  PRICES["onprem"]["transit_min_month"])
    return {"appliances": n * (c["appliance_capex"] / c["appliance_life_months"] + c["appliance_colo_month"]),
            "transit": transit, "staff": staff(max(n / c["appliances_per_fte"], PRICES["onprem"]["min_fte"]))}


PROFILES = {"variable (peak 3x avg)": 3.0, "steady (peak 1.2x avg)": 1.2}
CONTROL_SCALES = {"small (8 vCPU avg)": 8, "medium (200 vCPU avg)": 200, "large (5,000 vCPU avg)": 5_000}
DELIVERY_SCALES = {"10 TB/month": 10, "1 PB/month": 1_000, "100 PB/month": 100_000}


def crossing(xs, cloud_fn, own_fn):
    diff = [total(cloud_fn(x)) - total(own_fn(x)) for x in xs]
    for x, d0, d1 in zip(xs[1:], diff[:-1], diff[1:]):
        if d0 < 0 <= d1:
            return x
    return None


def control_breakeven(ratio):
    return crossing(np.logspace(0, 4.5, 500), lambda v: control_cloud("aws", v, ratio),
                    lambda v: control_onprem(v, ratio))


def delivery_breakeven():
    return crossing(np.logspace(0, 6, 500), lambda t: delivery_cloud("aws", t), delivery_own)


def chart(path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    ax = axes[0]
    xs = np.logspace(0, 4.5, 200)
    for (pname, ratio), ls in zip(PROFILES.items(), ["-", "--"]):
        short = pname.split()[0]
        ax.plot(xs, [total(control_cloud("aws", x, ratio)) for x in xs], color="#c80", ls=ls, label=f"AWS, {short}")
        ax.plot(xs, [total(control_onprem(x, ratio)) for x in xs], color="#555", ls=ls, label=f"On-prem, {short}")
        be = control_breakeven(ratio)
        if be:
            ax.axvline(be, color="#b33", ls=ls, lw=0.7)
            ax.annotate(f"break-even ~{be:,.0f} vCPU\n({short})", (be, total(control_onprem(be, ratio))),
                        fontsize=7, color="#b33", xytext=(5, -28 if ratio > 2 else 12), textcoords="offset points")
    ax.set_title("Control plane (APIs, recommendations, billing)")
    ax.set_xlabel("average compute demand (vCPU)")
    ax.set_ylabel("estimated USD per month")

    ax = axes[1]
    xs = np.logspace(0, 6, 200)
    ax.plot(xs, [total(delivery_cloud("aws", x)) for x in xs], color="#c80", label="AWS CloudFront")
    ax.plot(xs, [total(delivery_cloud("gcp", x)) for x in xs], color="#36c", label="GCP Cloud CDN")
    ax.plot(xs, [total(delivery_own(x)) for x in xs], color="#555", label="Own CDN (Open Connect style)")
    be = delivery_breakeven()
    if be:
        ax.axvline(be, color="#b33", ls="--", lw=0.7)
        ax.annotate(f"break-even ~{be:,.0f} TB/month", (be, total(delivery_own(be))), fontsize=7, color="#b33",
                    xytext=(5, 12), textcoords="offset points")
    ax.set_title("Video delivery (egress)")
    ax.set_xlabel("data delivered per month (TB)")
    for ax in axes:
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.grid(alpha=0.3, which="both")
        ax.legend(fontsize=8)
    fig.suptitle("S5 cost model (ESTIMATE): where cloud is cheaper and where owning is cheaper", fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)


def money(x):
    return f"${x:,.0f}" if x >= 10 else f"${x:,.4f}"


def main():
    lines = ["# S5 Cost Model (all figures are ESTIMATES)", "",
             f"Generated by `cost/cost_model.py`. Prices: {PRICES_CHECKED}. Region us-east-1 / us-east1, "
             "on-demand list prices, no free tier.", "",
             "## A. Cost of our experiment stages", "",
             "| Stage | USD per hour | USD per 30-day month | Steady-load throughput (req/s) | USD per 1,000 requests | What is included |",
             "|---|---|---|---|---|---|"]
    rps = measured_throughput()
    for name, (key, hourly, note) in stage_hourly().items():
        r = rps.get(key)
        per_k = f"${hourly / (r * 3600) * 1000:.6f}" if r else "-"
        lines.append(f"| {name} | {money(hourly)} | {money(hourly * HOURS_PER_MONTH)} | "
                     f"{f'{r:.1f}' if r else 'not measured yet'} | {per_k} | {note} |")
    lines += ["", "Throughput is the mean of the E0 steady-load runs (20 virtual users), so cost per 1,000 "
              "requests is at that load, not at saturation.", "",
              "## B. Netflix-like workload", "",
              "Netflix runs its control plane on AWS but delivers video from its own CDN (Open Connect). "
              "We price both halves separately.", "",
              "### B1. Control plane: monthly cost", "",
              "Per average vCPU: 0.05 TB stored and 0.05 TB of API egress per month. Cloud pays for average demand "
              "plus 30% headroom, with the always-on floor on a 1-year commitment, and needs a quarter of the "
              "operations staff per server. On-prem must own servers for peak demand plus 30% headroom "
              "(128 vCPU, $25k, 5-year life), with 1 engineer per 40 servers (minimum 1).", ""]
    for pname, ratio in PROFILES.items():
        lines += [f"**Demand profile: {pname}**", "", "| Scale | AWS | GCP | On-prem | Cheapest |", "|---|---|---|---|---|"]
        for sname, v in CONTROL_SCALES.items():
            costs = {"AWS": control_cloud("aws", v, ratio), "GCP": control_cloud("gcp", v, ratio),
                     "On-prem": control_onprem(v, ratio)}
            cheapest = min(costs, key=lambda k: total(costs[k]))
            lines.append(f"| {sname} | " + " | ".join(money(total(c)) for c in costs.values()) + f" | {cheapest} |")
        be = control_breakeven(ratio)
        lines += ["", f"AWS and on-prem break even at about **{be:,.0f} average vCPU**." if be else
                  "No break-even point in the modelled range.", ""]
    lines += ["### B2. Video delivery: monthly cost", "",
              "Cloud: CDN list price per GB with volume tiers. Own CDN: one $15k appliance per 20 Gbps of peak "
              "(4-year life, $300/month space and power), placed inside ISPs so only 30% of peak traffic uses paid "
              "transit, minimum 1 engineer.", "",
              "| Volume | AWS CloudFront | GCP Cloud CDN | Own CDN | Cheapest |", "|---|---|---|---|---|"]
    for sname, tb in DELIVERY_SCALES.items():
        costs = {"AWS": delivery_cloud("aws", tb), "GCP": delivery_cloud("gcp", tb), "Own CDN": delivery_own(tb)}
        cheapest = min(costs, key=lambda k: total(costs[k]))
        lines.append(f"| {sname} | " + " | ".join(money(total(c)) for c in costs.values()) + f" | {cheapest} |")
    be = delivery_breakeven()
    lines += ["", f"CloudFront and an own CDN break even at about **{be:,.0f} TB per month**." if be else
              "No break-even point in the modelled range.", ""]
    lines += ["### Cost breakdown: control plane at 5,000 vCPU, variable demand", "",
              "| Item | AWS | On-prem |", "|---|---|---|"]
    a, o = control_cloud("aws", 5_000, 3.0), control_onprem(5_000, 3.0)
    for k in a:
        lines.append(f"| {k} | {money(a[k])} | {money(o[k])} |")
    lines += ["", "## Assumptions (edit `PRICES`, `CDN_TIERS` and `OWN_CDN` in the script)", "", "```json",
              json.dumps({**PRICES, "cdn_tiers": CDN_TIERS, "own_cdn": OWN_CDN}, indent=2, default=str), "```", ""]
    (ROOT / "cost" / "cost_table.md").write_text("\n".join(lines), encoding="utf-8")
    chart(ROOT / "results" / "charts" / "cost_breakeven.png")
    print("\n".join(lines[:62]))


if __name__ == "__main__":
    main()
