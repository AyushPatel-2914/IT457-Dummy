# Week 3 Runbook: Build, Measure, Break

Step-by-step commands for every stage and experiment in the Week 2 plan (Section 7). Run all commands from the project root in Git Bash. Log the hours for each stage in `docs/effort-log.md` as you go.

> **Cost rule:** never leave AWS resources running between sessions. Every AWS section ends with `terraform destroy`. A full S2 session of about 3 hours costs roughly $0.30–$0.50 (see `cost/cost_table.md`).

---

## 0. One-time setup

| Tool | Why | Install |
|---|---|---|
| Docker Desktop | S0 and the local S2 stack; builds the image | already installed |
| Python 3.12 + packages | load generator, chaos scripts, analysis | `pip install -r requirements-tools.txt` |
| AWS CLI v2 | credentials, manual recovery in S1 | already installed |
| Terraform ≥ 1.5 | builds S1 and S2 | `winget install Hashicorp.Terraform` |

**AWS credentials.** `aws sts get-caller-identity` must succeed. With AWS Academy Learner Lab, copy the temporary credentials from "AWS Details" into `~/.aws/credentials` at the start of **every** session (they expire after a few hours).

**Your IP**, so only your load generator can reach the app:

```bash
export MYIP=$(curl -s https://checkip.amazonaws.com)/32
```

---

## 1. Local experiments (no AWS)

These are already scripted and were run on 2026-10-28:

```bash
bash loadtest/run_local_suite.sh      # ~65 min: S0 E0 x3, S0 E5, local-S2 E0, E4 x3 and E3 with breaker on/off
python loadtest/compare.py            # results/summary_table.md + charts
```

Individual runs:

```bash
docker compose -f app/docker-compose.yml up -d --build                     # S0 on :8080
python chaos/run_experiment.py --stage s0 --exp E0 --run 1 --url http://localhost:8080

BREAKER=on docker compose -f app/docker-compose.services.yml up -d --build # S2 shape on :8081
python chaos/run_experiment.py --stage local-s2 --exp E4 --tag breaker-on --run 1 --url http://localhost:8081
```

Tests: `python -m pytest app/tests chaos/test_chaos_monkey.py`

---

## 2. Shared AWS resources (once)

```bash
cd infra/shared
terraform init
terraform apply -var budget_email=you@example.com
# AWS Academy (cannot create IAM roles or budgets):
# terraform apply -var existing_instance_profile=LabInstanceProfile
cd ../..
infra/build_push.sh                    # builds app/ and pushes mini-netflix:latest to ECR
export IMAGE=$(terraform -chdir=infra/shared output -raw ecr_repository_url):latest
export PROFILE=$(terraform -chdir=infra/shared output -raw instance_profile_name)
```

The ECR repository costs a few cents a month. Destroy it at the end of the project (`terraform -chdir=infra/shared destroy`).

---

## 3. S1: lift-and-shift (one EC2 instance)

```bash
terraform -chdir=infra/s1 init
time terraform -chdir=infra/s1 apply -auto-approve -var image=$IMAGE -var instance_profile=$PROFILE -var allowed_cidr=$MYIP
export S1=$(terraform -chdir=infra/s1 output -raw url)
until curl -sf $S1/health; do sleep 5; done          # first boot takes 1-3 min
```

**E0 (steady load), 3 runs:**

```bash
for r in 1 2 3; do python chaos/run_experiment.py --stage s1 --exp E0 --run $r --url $S1 --probe-url $S1; done
```

**E1 (kill the only instance).** The script *stops* the instance 60 s into the run. Play the on-call engineer: when you see errors, restart it by hand and note the time.

```bash
python chaos/run_experiment.py --stage s1 --exp E1 --run 1 --url $S1 --probe-url $S1 &
# after the stop event appears (about 60 s in), when you notice the outage:
aws ec2 start-instances --instance-ids $(terraform -chdir=infra/s1 output -raw instance_id)
wait
```

Repeat for runs 2 and 3. Record in the report how long it took a human to notice and act. The automated part (boot plus containers) is visible in `watch.csv` (`probe_ok`).

> A stopped-then-started instance gets a **new public IP**. Re-read it with `terraform -chdir=infra/s1 refresh && export S1=$(terraform -chdir=infra/s1 output -raw url)` before the next run.

**Teardown:** `terraform -chdir=infra/s1 destroy -auto-approve`

---

## 4. S2: refactored (ALB + Auto Scaling Group + RDS)

```bash
terraform -chdir=infra/s2 init
time terraform -chdir=infra/s2 apply -auto-approve -var image=$IMAGE -var instance_profile=$PROFILE -var allowed_cidr=$MYIP
# RDS takes ~5-10 min to create.
export S2=$(terraform -chdir=infra/s2 output -raw url)
export ASG=$(terraform -chdir=infra/s2 output -raw asg_name)
export TG=$(terraform -chdir=infra/s2 output -raw catalogue_target_group)
until curl -sf $S2/health; do sleep 10; done
W="--asg $ASG --target-group $TG"
```

| Experiment | Command (repeat with `--run 2`, `--run 3`) |
|---|---|
| E0 steady | `python chaos/run_experiment.py --stage s2 --exp E0 --run 1 --url $S2 $W` |
| E1 random instance kills | `python chaos/run_experiment.py --stage s2 --exp E1 --run 1 --url $S2 $W` |
| E2 lose an AZ | `python chaos/run_experiment.py --stage s2 --exp E2 --run 1 --url $S2 $W --az us-east-1a` |
| E5 ramp / scale-out | `python chaos/run_experiment.py --stage s2 --exp E5 --run 1 --url $S2 $W --duration 900` (longer, so scale-out has time to happen) |
| E3 latency, breaker on | `python chaos/run_experiment.py --stage s2 --exp E3 --tag breaker-on --run 1 --url $S2 $W` |
| E4 recs down, breaker on | `python chaos/run_experiment.py --stage s2 --exp E4 --tag breaker-on --run 1 --url $S2 $W` |

Wait until `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $ASG` shows 2 healthy InService instances before starting the next run. After E5 wait for scale-in (about 15 min) or set the desired capacity back to 2.

If 20 VUs do not push CPU past 50% in E5, raise the ramp: edit `--ramp-to` in `chaos/run_experiment.py` or run `loadtest/loadgen.py` directly with `--vus 10 --ramp-to 300`.

**Breaker off** for the E3/E4 comparison:

```bash
terraform -chdir=infra/s2 apply -auto-approve -var image=$IMAGE -var instance_profile=$PROFILE -var allowed_cidr=$MYIP -var breaker=off
aws autoscaling start-instance-refresh --auto-scaling-group-name $ASG   # replaces instances with the new setting (~5 min)
# then run E3 and E4 with --tag breaker-off
```

**Optional, AWS FIS** (not available on most AWS Academy accounts): apply with `-var enable_fis=true`, then
`aws fis start-experiment --experiment-template-id <id from terraform output fis_templates>` while
`loadtest/loadgen.py` and `chaos/watch.py` run. Compare the result with the boto3 Chaos Monkey run of the same experiment.

**Evidence to capture** (screenshots into `results/screenshots/`): ALB target group health during a kill, ASG activity history showing the replacement, the CloudWatch CPU graph during E5, and the `terraform apply` output.

**Teardown:** `terraform -chdir=infra/s2 destroy -auto-approve`, then check the EC2 console shows no running `mini-netflix` instances.

---

## 5. Analysis and cost

```bash
python loadtest/compare.py      # all stages: results/summary_table.md, results/charts/*.png
python cost/cost_model.py       # cost/cost_table.md (now uses measured S1/S2 throughput)
```

Copy the numbers into `docs/week3-results.md` and fill the hypothesis table.
