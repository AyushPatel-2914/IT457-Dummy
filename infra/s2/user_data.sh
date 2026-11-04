#!/bin/bash
# S2 instance: catalogue, recommendations and auth containers on the host network, so the
# catalogue reaches recommendations on 127.0.0.1:5002. The database is RDS, so the instance holds
# no state and can be replaced at any time.
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${registry}
docker pull ${image}
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
IID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
COMMON="--network host --restart unless-stopped -e INSTANCE_ID=$IID -e DATABASE_URL=${database_url} -e TOKEN_SECRET=${token_secret}"
docker run -d --name catalogue $COMMON -e SERVICE=catalogue -e PORT=5001 \
  -e RECS_URL=http://127.0.0.1:5002 -e BREAKER=${breaker} ${image}
docker run -d --name recommendations $COMMON -e SERVICE=recommendations -e PORT=5002 -e FAULTS_ENABLED=1 ${image}
docker run -d --name auth $COMMON -e SERVICE=auth -e PORT=5003 ${image}
