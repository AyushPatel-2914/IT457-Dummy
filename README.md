# IT457 Cloud Computing Case Study: Netflix's AWS Migration and Chaos Engineering

**Topic:** Netflix → AWS migration, Chaos Monkey and resilience
**Theme match:** Migration and Transformation (primary), Scalability (secondary)

---

## 1. Case study summary (Week 1 material)

| Item | Key points (verify against the primary sources before submitting) |
|---|---|
| **Problem** | In August 2008 a major database corruption in Netflix's own data center stopped DVD shipping for about 3 days. Netflix decided a vertically scaled, single-point-of-failure data center was too risky for a fast-growing streaming business. |
| **Decision** | Move to AWS and rebuild as distributed microservices. The migration took about 7 years and finished around January 2016, when the last data center pieces (billing) were shut down. |
| **Architecture changes** | Monolith → hundreds of microservices; Oracle → Cassandra (NoSQL) and later DynamoDB; services on EC2 Auto Scaling Groups behind ELB; S3 for storage; multi-region (US-East, US-West, EU); Open Connect (own CDN) for video delivery. |
| **Resilience practices** | Chaos Monkey (2010–11, kills random instances), then the Simian Army (Latency Monkey, Chaos Gorilla for an AZ, Chaos Kong for a whole region), and later ChAP (Chaos Automation Platform). Plus Hystrix circuit breakers and regional failover drills. |
| **Outcomes** | Higher availability, elastic scaling and global expansion. Engineers design for failure. Netflix open-sourced much of its stack (Eureka, Hystrix, Zuul, Chaos Monkey). |
| **Cost angle** | Netflix argued that AWS gave elasticity and fewer large capital purchases. Exact savings are not publicly documented, so we will model cost ourselves. |

### Primary sources to cite
- Netflix Tech Blog: "Four Reasons We Choose Amazon's Cloud as Our Computing Platform" (2010)
- Netflix Tech Blog: "Completing the Netflix Cloud Migration" (Feb 2016)
- Netflix Tech Blog: "The Netflix Simian Army" (2011) and "Chaos Engineering Upgraded" (ChAP)
- Netflix Chaos Monkey GitHub repo (Netflix/chaosmonkey)
- AWS case study page: Netflix on AWS; AWS re:Invent talks (Netflix architecture)
- Book: *Chaos Engineering* (Rosenthal, Jones et al., O'Reilly) and principlesofchaos.org
- Netflix investor letters or 10-K filings (for scale and cost context)

---

## 2. Project ideas (pick one)

### Idea A: "Mini-Netflix": migrate, then break it on purpose (combined migration and chaos)
Take a small monolith app (for example a movie catalogue with a database) running in local Docker.
1. Lift-and-shift it to one EC2 VM (the "2008 to early AWS" stage).
2. Refactor it into 2–3 services (catalogue, recommendations, auth) behind an ALB with an Auto Scaling Group, and move the DB to a managed service (RDS or DynamoDB).
3. Run a Chaos Monkey-style script that randomly terminates instances, and measure availability, latency and recovery time with k6 or Locust.
4. Document effort and cost at each stage.

*Covers:* the migration exercise, the scalability exercise, and the Chaos Monkey part of the case.

### Idea B: Chaos engineering lab only
Deploy one autoscaled service. Run experiments: kill an instance, kill all instances in one AZ, inject latency, exhaust CPU. Compare "no resilience" and "with resilience" designs.

*Covers:* resilience in depth, but weak on the migration side of the topic.

### Idea C: Multi-region failover ("Chaos Kong" simulation)
Deploy the same app in two AWS regions with Route 53 health-check failover. Simulate a regional outage, then measure failover time and data loss.

*Covers:* the most advanced resilience concept. Costs more, is harder to set up, and carries more risk of overruns.

### Idea D: Cost and repatriation model: Netflix on-prem vs AWS vs GCP
Use the AWS and GCP pricing calculators to model a Netflix-like workload (storage, compute, egress) and compare with an on-premises estimate.

*Covers:* the cost exercise only. It is safe and cheap, but there is no hands-on build, so the Week 3 "build the core of the exercise" requirement is weak.

### Idea E: Serverless re-architecture of one Netflix component
Rebuild one piece (for example a thumbnail or metadata API) with Lambda and API Gateway. Measure cold start and cost per 1,000 requests versus EC2.

*Covers:* the serverless exercise. Netflix itself is mostly not serverless, so the link to the case is weaker.

---

## 3. Comparison and recommendation

| Criteria | A: Mini-Netflix | B: Chaos lab | C: Multi-region | D: Cost model | E: Serverless |
|---|---|---|---|---|---|
| Fit to the topic (migration **and** chaos) | Excellent | Good | Good | Weak | Weak |
| Hands-on build | High | High | High | None | Medium |
| Measurable results (latency, scaling, cost) | All three | Two | Two | Cost only | Two |
| Risk and AWS cost | Low–medium | Low | Medium–high | None | Low |
| Feasible in 3 weeks | Yes | Yes | Tight | Yes | Yes |
| Viva talking points | Many | Many | Many | Few | Some |

### Recommended: Idea A, with a small cost model from Idea D added

**Why this gets the best marks:**
1. It matches the **whole** topic. The migration story (monolith to cloud microservices) and Chaos Monkey/resilience are both reproduced at small scale.
2. It ticks every Week 3 requirement: a built core, **latency, scaling behaviour and cost** all measured, plus testing.
3. It produces strong charts (response time vs instance count, availability during chaos, recovery time), which graders like to see.
4. The plan is incremental. If time runs out, Stage 1 and 2 results are still a valid report, and chaos testing adds the extra credit.
5. It stays inside the free tier or a few dollars of AWS credit.
6. It gives a clear story for the viva: "Netflix did this over 7 years; we reproduced the journey in miniature and measured it."

---

## 4. Detailed plan for Idea A

### 4.1 Experiment design

| Stage | What we build | What we measure |
|---|---|---|
| **S0: Baseline** | Flask or Node app plus Postgres/SQLite in local Docker | Local latency with k6/Locust |
| **S1: Lift-and-shift** | Same container on one EC2 (t3.micro/small) | Latency, setup effort (hours), monthly cost |
| **S2: Refactor** | Split into services, ALB + Auto Scaling Group (min 2, max 4), DB moved to RDS or DynamoDB | Response time vs instance count under load, scale-out time, cost |
| **S3: Chaos** | Python/boto3 script ("mini Chaos Monkey") that terminates a random instance every N minutes; optionally AWS Fault Injection Service | Error rate, availability %, time to recover (MTTR), latency spike |
| **S4: Compare** | S1 (single VM) vs S2 (resilient) under the same chaos | Show that S1 goes down and S2 self-heals |
| **S5: Cost model** | AWS vs GCP calculator and on-prem estimate for the same workload | Monthly cost table and break-even discussion |

### 4.2 Metrics and charts to produce
- Response time (p50/p95) vs number of instances
- Requests per second vs time, with instance-count overlay (autoscaling behaviour)
- Availability and error rate during the chaos run (timeline with kill events marked)
- MTTR for each failure type
- Cost per stage and cost per 1,000 requests
- Effort table (hours) per migration stage

### 4.3 Architecture diagram (draw in draw.io for the report)
- Before: browser → single VM (app + DB)
- After: browser → Route 53 → ALB → ASG (2–4 EC2 across 2 AZs) → RDS/DynamoDB, CloudWatch for metrics, chaos script as an external actor

### 4.4 Tools
AWS (EC2, ALB, Auto Scaling, RDS/DynamoDB, CloudWatch, optionally FIS), Docker, k6 or Locust, Python + boto3, matplotlib for charts, draw.io, AWS and GCP pricing calculators.

### 4.5 Cost control (important)
- Set an AWS Budget alert at about $5 before doing anything else
- Use t3.micro or t3.small instances and stop or terminate everything after each session
- Keep load tests short (5–10 minutes)
- Check whether the college provides AWS Academy or credits

---

## 5. Timeline (matches the course plan)

| Week | Tasks | Deliverable |
|---|---|---|
| **1** | Read the primary sources above and extract architecture, cost and outcome data. Choose Idea A. | One-page summary: sources found and salient points (Section 1 is the starting draft) |
| **2** | Detailed case analysis: before and after architecture diagram, problem and solution. Write the exercise plan (Section 4). Assign roles. | 10-page report |
| **3** | Build S0–S2, run load tests, build and run the chaos script (S3–S4), cost model (S5). Save raw data and screenshots. | Report add-ons with results |
| **4** | Merge everything, polish the charts, proofread, check references. | Final report submission |
| **5** | Rehearse the viva and prepare a demo (or a recorded backup demo). | Project viva |

---

## 6. Team roles (adjust to your team size)

| Role | Responsibilities |
|---|---|
| Research lead | Sources, case summary, timeline of the Netflix migration, references |
| Cloud engineer | AWS setup, S1 and S2 deployment, Auto Scaling, DB migration |
| Resilience and testing engineer | Chaos script, k6/Locust tests, data collection |
| Analysis and report lead | Charts, cost model, report assembly, viva slides |

Everyone should understand the full pipeline well enough to answer viva questions.

---

## 7. Suggested 10-page report outline

1. Introduction and objectives (0.5 page)
2. Netflix case background and problem (1 page)
3. Migration journey and timeline (1 page)
4. Architecture before and after, with diagrams (1.5 pages)
5. Chaos engineering and resilience practices (1.5 pages)
6. Outcomes, costs and lessons learned (1 page)
7. Exercise plan and design (1.5 pages)
8. Results (added in Week 3): charts and analysis (1.5 pages)
9. Critical discussion: limits of our simulation, how it differs from Netflix scale (0.5 page)
10. Conclusion and references

---

## 8. Likely viva questions to prepare for
- Why did Netflix leave its own data center, and why did the migration take 7 years?
- Why microservices and NoSQL instead of the monolith and Oracle?
- What is Chaos Monkey, and how is it different from Chaos Gorilla and Chaos Kong?
- How does an Auto Scaling Group recover from a terminated instance, and what determines recovery time?
- What did your results show, and what would change at Netflix's scale?
- Where is the cloud more expensive than on-prem? (Netflix still runs its own CDN, Open Connect.)
- What were the limits of your experiment, and what would you do with more time or budget?

---

## 9. Tips for scoring well
- Cite primary sources (Netflix Tech Blog, AWS pages), not only secondary articles.
- Mark what is **public fact** and what is **your own estimate**, especially for costs.
- Show raw measurements and the method, so results are reproducible.
- Include a "limitations" section. Graders value honest analysis.
- Keep a running log of effort in hours for the migration comparison.
- Take screenshots and save scripts and CSVs in this repo as evidence for the viva.

---

## 10. Suggested repo layout

```
IT457/Project/
├── README.md
├── docs/            # Week 1 summary, report drafts, diagrams
├── app/             # Mini-Netflix app (Dockerfile, source)
├── infra/           # AWS setup notes or CloudFormation/Terraform
├── chaos/           # chaos_monkey.py
├── loadtest/        # k6 or Locust scripts
├── results/         # raw CSVs, charts, screenshots
└── cost/            # pricing calculator exports and cost table
```
#   I T 4 5 7 - D u m m y  
 #   I T 4 5 7 - D u m m y  
 