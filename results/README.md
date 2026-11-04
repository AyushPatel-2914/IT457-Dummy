# Results layout

```
results/
├── <stage>/<experiment>[-<variant>]/run<N>/
│   ├── requests.csv   every request: start/end time, endpoint, status, latency, serving instance, recs source
│   ├── events.csv     chaos actions with timestamps (kills, faults)
│   ├── watch.csv      AWS only: ASG / target-group health every 2 s
│   ├── summary.json   computed by loadtest/analyze.py
│   └── timeline.png   availability, latency, throughput (and instances) over time, chaos events marked
├── charts/            comparison charts from loadtest/compare.py and cost/cost_model.py
├── summary_table.md   one row per stage and experiment (median and range over runs)
└── local_suite.log    console log of loadtest/run_local_suite.sh
```

Stages: `s0` laptop Docker monolith, `local-s2` the S2 service split run locally in Docker, `s1` one EC2 instance, `s2` ALB + ASG + RDS.
Experiments: `e0` steady load, `e1` instance kills, `e2` AZ loss, `e3` latency injection, `e4` recommendations down, `e5` load ramp.

Raw CSVs are the evidence: every number in the report can be recomputed with `python loadtest/analyze.py <run dir>`.
