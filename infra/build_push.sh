#!/usr/bin/env bash
# Build the app image and push it to the ECR repository created by infra/shared.
# Usage: infra/build_push.sh [tag]     (default tag: latest)
set -euo pipefail
cd "$(dirname "$0")"
TAG=${1:-latest}
REPO=$(terraform -chdir=shared output -raw ecr_repository_url)
REGION=$(echo "$REPO" | cut -d. -f4)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}"
docker build --platform linux/amd64 -t "$REPO:$TAG" ../app
docker push "$REPO:$TAG"
echo "pushed $REPO:$TAG"
