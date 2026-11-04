# Mini-Netflix: What We Are Making (Plain-English Guide)

This guide explains our project from zero. You don't need to know cloud computing to follow it. The main README has the plan and the timeline. This file explains the *why* and the *what*.

---

## 1. The story we are studying

In **August 2008**, Netflix had a serious problem. The database in their own data center broke (it got corrupted). For about **3 days** they could not ship DVDs to customers.

The cause was simple: everything ran in **one place**. If that place had a problem, everything stopped. That is called a **single point of failure**.

Netflix decided to:
1. Leave its own data center and move to **Amazon Web Services (AWS)**, a cloud provider where you rent computers by the hour.
2. Rebuild the software as many small pieces, called **microservices**, so one broken piece doesn't take everything down.
3. Deliberately **break things on purpose** to make sure the system could survive failures. The tool for this is called **Chaos Monkey**. It randomly shuts down servers while the system is running.

The move took about **7 years** and finished around **January 2016**.

Our course topic is this story: **Netflix's move to AWS and chaos engineering**.

---

## 2. What our project is

We can't rebuild Netflix. Instead we build a **tiny version of Netflix's journey** and measure what happens.

> Netflix did this over 7 years. We reproduce the same journey in miniature and measure it.

In one sentence: **we take a small movie-catalogue web app, move it to AWS in two stages, then randomly kill its servers and see which version survives.**

---

## 3. Words you need to know

| Word | Simple meaning |
|---|---|
| **Cloud / AWS** | Renting computers over the internet instead of owning them. |
| **EC2** | An AWS rented computer (a "virtual machine", or VM). |
| **Docker / container** | A box that packs an app with everything it needs, so it runs the same everywhere. |
| **Monolith** | One big program that does everything. |
| **Microservices** | Many small programs, each doing one job (for example catalogue, recommendations, login). |
| **Load balancer (ALB)** | A traffic officer. It sends each visitor to one of several servers. |
| **Auto Scaling Group (ASG)** | A manager that keeps a set number of servers running. It adds servers when busy and replaces dead ones automatically. |
| **RDS / DynamoDB** | Databases run by AWS, so we don't manage them ourselves. |
| **Availability** | The percentage of time the app works. 99% means it was down 1% of the time. |
| **Latency** | How long a request takes to get an answer. p50 is the typical request. p95 is the slow ones. |
| **MTTR** | Mean Time To Recover. How long the app takes to come back after something breaks. |
| **Chaos engineering** | Breaking things on purpose, in a controlled way, to learn how the system behaves. |
| **Load test** | Sending lots of fake visitors to the app to see how it copes (we use k6 or Locust). |

---

## 4. The app

A small **movie catalogue** website built with Flask (Python) or Node.js, plus a database (Postgres or SQLite). It can list movies, show details, log in a user, and suggest movies. The app is deliberately simple, because the project is about *where and how it runs*, not about the app itself.

---

## 5. The stages (the core of the project)

We build the project in steps. Each step is measured, so we can compare them.

### S0: Baseline (on your laptop)
Run the app in Docker on your own machine. This is our "before the cloud" reference. We measure how fast it responds.

**Real-world parallel:** Netflix's own data center.

### S1: Lift-and-shift (one server on AWS)
Take the *same* app and put it on **one EC2 machine**. Nothing changes in the code. This is the quick, easy way to "move to the cloud".

We measure: response time, how many hours the move took, and the monthly cost.

**Real-world parallel:** Netflix's early days on AWS. Moving is easy, but it is still one server. If it dies, the app dies.

```
Browser  ->  [ One EC2 server: app + database ]
```

### S2: Refactor (the proper cloud design)
Now we redesign the app the cloud way:
- Split it into **2-3 services** (catalogue, recommendations, auth).
- Put a **load balancer** in front.
- Run **2 to 4 servers** in an Auto Scaling Group, spread over **2 data-center zones** (Availability Zones).
- Move the database to a **managed database** (RDS or DynamoDB).
- Watch everything with **CloudWatch** (AWS's monitoring dashboard).

```
Browser -> Route 53 (DNS) -> Load Balancer -> [ Server 1 | Server 2 | ... up to 4 ] -> Managed database
                                                (in 2 zones, auto scaling)
                                CloudWatch watches it all
```

We measure: response time as the number of servers changes, how fast it adds servers when busy, and the cost.

**Real-world parallel:** Netflix's final design, with microservices, Auto Scaling, and Cassandra/DynamoDB.

### S3: Chaos (break it on purpose)
We write a small Python script (using the AWS library `boto3`) called our **mini Chaos Monkey**. Every few minutes it **picks a random server and terminates it**. While that happens, a load test keeps sending visitors, so we can see the damage.

We measure:
- **Error rate and availability** (did visitors get errors?)
- **MTTR** (how long until things were healthy again?)
- **Latency spikes** (did the app slow down?)

(Optional extra: AWS Fault Injection Service, a ready-made AWS tool for this.)

### S4: Compare
Run the *same* chaos on S1 and on S2.

**What we expect to show:**
- **S1 (single server):** the server is killed, the app goes down, and it stays down until someone fixes it by hand.
- **S2 (resilient):** a server is killed, the load balancer stops using it, the Auto Scaling Group starts a replacement, and visitors barely notice.

This is the main result of the project. It shows *why* Netflix built things this way.

### S5: Cost model
Using the AWS and Google Cloud pricing calculators, we estimate the monthly cost of a Netflix-like workload (storage, computing, data transfer) on AWS, on GCP, and on our own on-premises hardware. We then discuss where each is cheaper.

Netflix's exact savings are not public, so these numbers are **our own estimates**, and we will label them that way.

---

## 6. What we measure and what we produce

| Measurement | Chart or table |
|---|---|
| Response time (p50/p95) vs number of servers | Line chart |
| Requests per second over time, with server count overlaid | Autoscaling chart |
| Availability and errors during chaos, with kill events marked | Timeline chart |
| Recovery time (MTTR) for each failure | Table |
| Cost per stage and per 1,000 requests | Table |
| Hours of work per stage | Effort table |

Everything is saved as raw data (CSV files), scripts and screenshots, so anyone can repeat our experiment.

---

## 7. Why this is a good project

1. It covers **both** parts of the topic: the migration and the chaos engineering.
2. It measures **latency, scaling and cost**, which the course asks for.
3. It builds up step by step. If time runs out, S0-S2 is still a complete report, and chaos is the bonus.
4. It is cheap: a few dollars of AWS credit, if we are careful.
5. It has a clear viva story: *"Netflix took 7 years. We did it in miniature, and here is what we measured."*

---

## 8. Keeping the AWS bill small

Cloud servers cost money for every hour they run.
- **First thing:** set an AWS Budget alert at about **$5**.
- Use small machines (`t3.micro` or `t3.small`).
- **Turn off or delete everything** at the end of each work session.
- Keep load tests short (5-10 minutes).
- Ask the college whether we can use AWS Academy or free credits.

---

## 9. Be honest about the limits

Our experiment is a toy compared to Netflix. We have a handful of servers, not thousands. Our traffic is fake. So the report will include a **limitations** section: what our results can show, and what they can't.

We also keep a clear split between **public facts** (from Netflix and AWS sources) and **our own estimates** (especially costs).

---

## 10. The 5-week plan

| Week | What happens | Output |
|---|---|---|
| 1 | Read the Netflix and AWS sources. Choose Idea A. | One-page summary (`docs/week1-summary.md`) |
| 2 | Write the case analysis, draw before/after diagrams, write the experiment plan. | 10-page report |
| 3 | Build S0-S2, run load tests, build and run the chaos script, make the cost model. | Report add-ons with results |
| 4 | Merge, polish charts, proofread, check references. | Final report |
| 5 | Practise for the viva and prepare a demo. | Viva |

---

## 11. Who does what

| Role | Job |
|---|---|
| Research lead | Sources, Netflix timeline, references |
| Cloud engineer | AWS setup, S1 and S2, Auto Scaling, database move |
| Resilience and testing engineer | Chaos script, load tests, data collection |
| Analysis and report lead | Charts, cost model, report, slides |

Everyone should understand the whole pipeline, because the viva questions can go to anyone.

---

## 12. Where things live in this folder

```
Project/
├── README.md             # the original plan and timeline
├── README-EXPLAINED.md   # this file
├── docs/                 # week 1 summary, effort log, report drafts, diagrams
├── app/                  # the Mini-Netflix app (Dockerfile + source)
├── infra/                # AWS setup notes or Terraform/CloudFormation
├── chaos/                # chaos_monkey.py
├── loadtest/             # k6 or Locust scripts
├── results/              # raw CSVs, charts, screenshots
└── cost/                 # pricing exports and the cost table
```

---

## 13. The idea in one picture

```
Laptop (S0) --> 1 AWS server (S1) --> Load balancer + many servers + managed DB (S2)
                       |                              |
                       +---------- Chaos script kills servers (S3) ----------+
                       |                              |
                  App goes DOWN                  App heals itself       --> Compare (S4) + Cost (S5)
```

**Takeaway:** Moving to the cloud is not enough. The *design* is what makes a system survive failure, and the way to prove it is to break it on purpose.
