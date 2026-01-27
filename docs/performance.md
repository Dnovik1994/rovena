# Performance & Load Testing

## Baseline Setup
- Stack: nginx + FastAPI + MySQL + Redis + Celery.
- Load test tool: Locust.

## Load Test Results (Template)
**Date:** YYYY-MM-DD  
**Environment:** local/staging/prod  
**Test command:**
```
locust -f locustfile.py -u 100 -r 10 --headless -t 10m --host http://localhost
```

### Results
- **/api/v1/auth/telegram**: RPS ___, p95 ___ms, errors ___%
- **/api/v1/campaigns/{id}/start**: RPS ___, p95 ___ms, errors ___%
- **/api/v1/admin/stats**: RPS ___, p95 ___ms, errors ___%

### Notes
- Cache hit ratio:
- DB CPU/IO:
- Redis CPU/IO:

## Optimization Checklist
- Apply Alembic index migration `0017_add_performance_indexes`.
- Verify cache hits in logs (`Cache hit for key user:` / `tariff:`).
- Monitor worker concurrency and queue length.
