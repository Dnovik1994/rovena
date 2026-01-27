# Load Test Template

## Setup
- Export required env vars:
  - `LOCUST_INIT_DATA`
  - `LOCUST_PROJECT_ID`
  - `LOCUST_SOURCE_ID` (optional)
  - `LOCUST_TARGET_ID` (optional)
  - `LOCUST_CAMPAIGN_ID` (optional)
  - `LOCUST_ADMIN_TOKEN`

## Command
```
locust -f locustfile.py -u 50 -r 5 --headless -t 1m --host http://localhost:8000
```

## Results
- RPS:
- p95 latency:
- failures:
- notes:
