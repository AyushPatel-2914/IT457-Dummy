# Week 1 Summary: Netflix's AWS Migration and Chaos Engineering

**Project:** "Mini-Netflix: migrate, then break it on purpose" (with a small Idea D cost model)
**Theme:** Migration and Transformation (primary), Scalability (secondary)

> Status: DRAFT. Every row marked **[verify]** comes from the project README or from memory and has not yet been checked against the primary source. Replace each with a figure and a citation before submission.
> Legend: **Fact** = stated in a public source. **Estimate** = our own calculation. **Our addition** = something we add that Netflix did not do.
> Reference numbers like [R3] point to Section 8.

## 1. Problem

- **The incident.** In Aug 2008 a major database corruption in Netflix's own data center stopped DVD shipping for about 3 days. **[verify]** (Fact, [R1], [R2])
- **Why it mattered.** The business was shifting from DVDs by mail to streaming. A streaming service has to be up all the time, because there is no "ship it tomorrow" fallback.
- **Root weakness.** The system was a vertically scaled monolith on a relational database (Oracle) in one data center. Every layer was a single point of failure, and the only way to grow was to buy bigger hardware.
- **Capacity problem.** Capacity had to be bought months ahead for peak demand. Demand was growing fast and was hard to predict, so Netflix risked either running out of capacity or paying for idle machines.
- **Conclusion Netflix reached.** It did not want to get better at running data centers. It wanted to remove the single points of failure and stop owning undifferentiated infrastructure. **[verify]** ([R1])

## 2. Decision

- Move to AWS and rebuild as distributed microservices, rather than lift-and-shift the monolith.
- Netflix chose a public cloud over building a second data center because it could add capacity in minutes and avoid very large capital purchases. **[verify]** ([R1])
- Migration took about 7 years (2009 to 2016). The last data center pieces (billing) were shut down around Jan 2016. **[verify]** ([R3])
- The order was deliberate: customer-facing streaming services moved first, and sensitive systems such as billing moved last. **[verify]** ([R3])
- Engineering culture changed with the architecture. Teams owned their services end to end ("you build it, you run it") instead of handing code to a separate operations group. **[verify]** ([R2])

## 3. Architecture changes

| Before | After | Why it helps |
|---|---|---|
| Monolith | Hundreds of microservices | A failure or deploy affects one service, not the whole site |
| Oracle (single relational DB) | Cassandra (NoSQL, multi-node, multi-region), later DynamoDB | No single DB host to lose; writes keep working through node failures |
| Own data center | EC2 Auto Scaling Groups behind ELB, S3, multi-region (US-East, US-West, EU) | Elastic capacity; a region can be evacuated |
| Third-party CDN / own delivery | Open Connect (own CDN, appliances placed inside ISPs) for video delivery | Cuts transit cost and keeps video traffic off the open internet |

All rows **[verify]** ([R1], [R3], [R5]).

Supporting services Netflix built or open-sourced to make this work:
- **Eureka**: service discovery, so instances can come and go.
- **Zuul**: edge gateway and routing.
- **Hystrix**: circuit breaker library that stops one slow dependency from taking down callers.
- **Spinnaker**: multi-cloud continuous delivery platform.
- **Ribbon**: client-side load balancing.

**[verify]** each ([R10]).

## 4. Resilience practices

- **Chaos Monkey (2010-11).** Randomly terminates production instances during business hours so that engineers must build services that survive instance loss. **[verify]** ([R4], [R6])
- **Simian Army.** The family of tools built on that idea: **[verify]** ([R4])
  - Latency Monkey: injects delays into client-server calls.
  - Conformity Monkey: finds instances that break best-practice rules.
  - Chaos Gorilla: takes out a whole Availability Zone.
  - Chaos Kong: takes out a whole region (simulates an AWS region failure).
- **ChAP (Chaos Automation Platform).** Runs a controlled experiment by sending a small slice of real traffic to an "experiment" group and comparing it with a "control" group, which limits blast radius. **[verify]** ([R7])
- **Failure-injection testing (FIT)** and regional failover drills, where traffic is shifted away from a region on purpose. **[verify]** ([R7], [R8])
- **Principles of Chaos.** The discipline was later formalised as: define steady state, hypothesise it continues, introduce real-world failures, try to disprove the hypothesis, minimise blast radius. ([R8], [R9])
- **Later change.** Chaos Monkey 2.0 was rebuilt to work with Spinnaker, and Hystrix was put into maintenance mode, with Netflix recommending Resilience4j-style libraries instead. **[verify]** ([R6], [R10])

## 5. Outcomes

- Higher availability: losing an instance, AZ, or (in drills) a region no longer means losing the service.
- Elastic scaling for daily and launch-day peaks, and expansion to many countries without building a data center in each.
- Engineers design for failure from the start, not as an afterthought.
- Open-sourced stack (Eureka, Hystrix, Zuul, Chaos Monkey, Spinnaker) that shaped the wider industry and the later "cloud native" movement.
- Trade-off to mention in the report: microservices add operational complexity, such as distributed tracing, many deploy pipelines and harder debugging. Netflix paid for this with heavy tooling.

## 6. Cost angle

- Netflix's stated reasons were elasticity, speed, and fewer large capital purchases, not a claim of lower unit cost. **[verify]** ([R1])
- Exact savings are not publicly documented. We model cost ourselves (**Estimate**, Week 3, `cost/`).
- Netflix still runs its own CDN (Open Connect) because at very high, steady video volume owning the delivery layer is cheaper than renting it. This is the key counter-example to "cloud is always cheaper" and a likely viva question. **[verify]** ([R5])
- Cost context (subscribers, content spend, cloud spend) can be taken from investor letters and 10-K filings ([R11]).
- Our cost model will report **cost per 1,000 requests** and **cost per stage**, so it is comparable across S1, S2 and the on-prem estimate.

## 7. What we plan to add beyond the case (new technology and ideas)

Netflix's 2010-2016 tooling is partly obsolete. We reproduce the same ideas with current tools, so the project is a reproduction and also a modernisation. All of this is **Our addition**.

| Idea | What we do | Why it adds value | Reference |
|---|---|---|---|
| **AWS Fault Injection Service (FIS)** | Run the same terminate/latency experiments as managed, auditable experiment templates with stop conditions, next to our boto3 "mini Chaos Monkey" | Compare a hand-rolled script with the managed service Netflix did not have in 2011 | [R12] |
| **Containers on ECS Fargate or EKS** | Add one extra stage (S2b) that runs the services as containers instead of EC2 instances | Compares scale-out time of VMs and containers, a real modern migration step | [R13] |
| **Infrastructure as Code (Terraform or CloudFormation)** | Build S1 and S2 from code, not the console | Reproducible environment, measurable setup effort, easy teardown to save money | [R14] |
| **Observability with Prometheus + Grafana, plus CloudWatch** | Dashboards showing latency, error rate and instance count during chaos | Gives clean charts for the report and shows steady-state metrics, as the chaos principles require | [R8], [R15] |
| **Resilience patterns in code** | Add circuit breaker, retry with backoff and timeout (Resilience4j or pybreaker) to the catalogue/recommendation call | Reproduces what Hystrix did; test with and without it | [R10], [R16] |
| **Graceful degradation** | When recommendations is down, catalogue returns a generic popular list | Same idea as Netflix's fallback behaviour; measure availability gain | [R7], [R16] |
| **Serverless variant (Lambda + API Gateway) for one service** | Optional: move the thumbnail/metadata endpoint, measure cold start and cost | Links to Idea E; shows a third architecture style in the migration path | [R17] |
| **AWS Well-Architected Reliability Pillar review** | Score S1 and S2 against its checklist | Gives a structured way to argue why S2 is better | [R16] |
| **SLO/error-budget framing** | Set an availability target (for example 99.9%) and check each stage against it | Turns "availability" into a pass/fail result | [R18] |
| **Cost optimisation experiment** | Compare On-Demand, Spot and a Savings Plan estimate for the ASG | Shows how Netflix-style stateless services can use cheaper capacity | [R19] |

Priority if time is short: keep Terraform, Prometheus/Grafana, circuit breaker and FIS (high value, low cost). Treat Fargate/EKS, Lambda and Spot as stretch goals.

## 8. References and sources (reading tracker)

Status in the last column: [ ] not read, [x] read. "Read by" and "Key data extracted" are filled in as the team reads each source.

### 8.1 Primary sources (Netflix and AWS)
| # | Source | Read by | Key data extracted | Done |
|---|---|---|---|---|
| R1 | Netflix Tech Blog, "Four Reasons We Choose Amazon's Cloud as Our Computing Platform" (Dec 2010) | | | [ ] |
| R2 | Netflix Tech Blog, "5 Lessons We've Learned Using AWS" (Dec 2010) | | | [ ] |
| R3 | Netflix Tech Blog (Y. Izrailevsky), "Completing the Netflix Cloud Migration" (Feb 2016) | | | [ ] |
| R4 | Netflix Tech Blog, "The Netflix Simian Army" (Jul 2011) | | | [ ] |
| R5 | Netflix Open Connect overview (openconnect.netflix.com) and Netflix Tech Blog posts on Open Connect | | | [ ] |
| R6 | GitHub: Netflix/chaosmonkey, and Netflix Tech Blog "Chaos Monkey Released Into The Wild" (2012) | | | [ ] |
| R7 | Netflix Tech Blog, "ChAP: Chaos Automation Platform" and "FIT: Failure Injection Testing" | | | [ ] |
| R10 | Netflix OSS (github.com/Netflix): Eureka, Zuul, Hystrix, Spinnaker | | | [ ] |
| R11 | Netflix investor letters and 10-K filings (scale and cost context) | | | [ ] |

### 8.2 Chaos engineering, academic and book sources
| # | Source | Read by | Key data extracted | Done |
|---|---|---|---|---|
| R8 | principlesofchaos.org | | | [ ] |
| R9 | Rosenthal, Jones et al., *Chaos Engineering: System Resiliency in Practice* (O'Reilly, 2020) | | | [ ] |
| R20 | Basiri et al., "Chaos Engineering," *IEEE Software* 33(3), 2016 | | | [ ] |
| R21 | Alvaro et al., "Automating Failure Testing Research at Internet Scale," ACM SoCC 2016 (Netflix collaboration) | | | [ ] |
| R22 | DeCandia et al., "Dynamo: Amazon's Highly Available Key-value Store," SOSP 2007 (background for Cassandra/DynamoDB choice) | | | [ ] |
| R23 | Lakshman and Malik, "Cassandra: A Decentralized Structured Storage System," ACM SIGOPS OSR 2010 | | | [ ] |

### 8.3 Sources for the modern additions
| # | Source | Read by | Key data extracted | Done |
|---|---|---|---|---|
| R12 | AWS Fault Injection Service documentation | | | [ ] |
| R13 | AWS documentation: Amazon ECS on Fargate / Amazon EKS | | | [ ] |
| R14 | Terraform AWS provider docs, or AWS CloudFormation user guide | | | [ ] |
| R15 | Prometheus and Grafana documentation; Amazon CloudWatch user guide | | | [ ] |
| R16 | AWS Well-Architected Framework, Reliability Pillar; Resilience4j docs | | | [ ] |
| R17 | AWS Lambda developer guide (cold starts, pricing) | | | [ ] |
| R18 | Beyer et al., *Site Reliability Engineering* (Google, O'Reilly 2016), chapters on SLOs and error budgets | | | [ ] |
| R19 | AWS pricing pages: EC2 On-Demand, Spot, Savings Plans; AWS and GCP pricing calculators | | | [ ] |

### 8.4 Background reading on migration and microservices
| # | Source | Read by | Key data extracted | Done |
|---|---|---|---|---|
| R24 | AWS Prescriptive Guidance, "Large migrations" and the "6 Rs" (rehost, replatform, refactor, etc.), to frame S1 vs S2 | | | [ ] |
| R25 | Fowler and Lewis, "Microservices," martinfowler.com (2014) | | | [ ] |
| R26 | AWS re:Invent talks on Netflix architecture and resilience (search the re:Invent channel on YouTube) | | | [ ] |

Note: before submission, add the exact URL, author and access date to each reference in the final citation style the course requires. Titles above are from memory and must be checked.

## 9. Project decision

Idea A chosen: it covers the migration story, scalability and Chaos Monkey in one incremental build.

| Stage | Content | Link to Netflix |
|---|---|---|
| S0 | Baseline monolith in Docker | The pre-2009 monolith |
| S1 | Lift-and-shift to one EC2 VM | Early cloud, "rehost" |
| S2 | Refactor to services + ALB + Auto Scaling + managed DB | Microservices on AWS, "refactor" |
| S3 | Chaos: boto3 script and AWS FIS | Chaos Monkey and Simian Army |
| S4 | Compare S1 and S2 under the same chaos | Why Netflix rebuilt rather than moved |
| S5 | Cost model (AWS vs GCP vs on-prem) | Idea D, elasticity vs ownership |

Added from Section 7: Terraform for all stages, Prometheus/Grafana dashboards, a circuit breaker with graceful degradation, and optional Fargate and Lambda variants.

## 10. Open items
- [ ] Verify all **[verify]** rows against sources and fill the tracker in Section 8
- [ ] Confirm the exact titles and URLs of the Netflix posts (several are from memory)
- [ ] Decide which Section 7 additions are in scope (suggested: Terraform, observability, circuit breaker, FIS)
- [ ] Assign team roles
- [ ] Set AWS Budget alert (~$5); check AWS Academy / college credits
- [ ] Keep `docs/effort-log.md` updated
