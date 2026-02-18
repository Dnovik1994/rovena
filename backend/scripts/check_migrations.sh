#!/usr/bin/env bash
set -euo pipefail

echo "Checking Alembic migration graph..."

# Count heads
HEAD_COUNT=$(alembic heads 2>/dev/null | wc -l)

if [[ "$HEAD_COUNT" -gt 1 ]]; then
    echo "ERROR: Multiple Alembic heads detected ($HEAD_COUNT):"
    alembic heads
    echo ""
    echo "Fix: run 'alembic merge heads -m \"merge\"' and commit the result"
    exit 1
fi

echo "OK: Single head detected"
alembic heads
exit 0
