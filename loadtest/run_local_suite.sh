#!/usr/bin/env bash
# Runs every experiment that does not need AWS: S0 baseline and the S2 service split locally.
# Runs are 5 minutes (not the 10 planned for AWS) to keep the local suite near one hour.
set -euo pipefail
cd "$(dirname "$0")/.."
D=300
RUN="python chaos/run_experiment.py --duration $D"
S2="docker compose -f app/docker-compose.services.yml"

wait_up() { for i in $(seq 1 60); do curl -sf "$1/health" >/dev/null && return; sleep 2; done; echo "not up: $1"; exit 1; }

# S0: monolith + Postgres in Docker
docker compose -f app/docker-compose.yml up -d --build
wait_up http://localhost:8080
for r in 1 2 3; do $RUN --stage s0 --exp E0 --run $r --url http://localhost:8080; done
$RUN --stage s0 --exp E5 --run 1 --url http://localhost:8080
docker compose -f app/docker-compose.yml down

# Local S2 with the circuit breaker on, then off
for b in on off; do
  BREAKER=$b $S2 up -d --build --force-recreate
  wait_up http://localhost:8081
  [ $b = on ] && $RUN --stage local-s2 --exp E0 --run 1 --url http://localhost:8081
  for r in 1 2 3; do $RUN --stage local-s2 --exp E4 --tag breaker-$b --run $r --url http://localhost:8081 --fault-at 60 --fault-for 120; done
  $RUN --stage local-s2 --exp E3 --tag breaker-$b --run 1 --url http://localhost:8081 --fault-at 60 --fault-for 120
done
$S2 down
echo "local suite done"
