#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

git pull origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml build --pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec worker alembic upgrade head

echo "✅ deploy complete"
