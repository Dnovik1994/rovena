#!/usr/bin/env bash
set -euo pipefail

docker volume rm rovena_postgres-data || true
docker volume rm rovena_mysql-data || true
