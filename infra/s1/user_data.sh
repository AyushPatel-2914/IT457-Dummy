#!/bin/bash
# S1: same containers as S0, on one VM. Containers restart automatically if the VM is restarted,
# but nothing replaces the VM if it is stopped or terminated.
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${registry}
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
IID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
docker network create minix
docker run -d --name db --network minix --restart unless-stopped \
  -e POSTGRES_USER=minix -e POSTGRES_PASSWORD=minix -e POSTGRES_DB=minix \
  -v pgdata:/var/lib/postgresql/data public.ecr.aws/docker/library/postgres:16-alpine
docker run -d --name app --network minix --restart unless-stopped -p 80:5000 \
  -e SERVICE=monolith -e DATABASE_URL=postgresql://minix:minix@db:5432/minix -e INSTANCE_ID=$IID \
  ${image}
