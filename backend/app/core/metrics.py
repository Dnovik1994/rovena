from prometheus_client import Counter, Gauge, Histogram

accounts_total = Gauge("accounts_total", "Total accounts")
accounts_by_status = Gauge("accounts_by_status", "Accounts by status", ["status"])

campaign_invites_success_total = Counter(
    "campaign_invites_success_total", "Successful invites"
)
campaign_invites_errors_total = Counter(
    "campaign_invites_errors_total", "Invite errors", ["error_type"]
)
celery_queue_length = Gauge("celery_queue_length", "Celery queue length")

# Auth observability
telegram_auth_reject_total = Counter(
    "telegram_auth_reject_total",
    "Rejected Telegram auth attempts",
    ["reason"],
)
verify_account_duration_seconds = Histogram(
    "verify_account_duration_seconds",
    "Time spent in verify_account Pyrogram call",
)

# ── Verify pipeline metrics ──
verify_fail_total = Counter(
    "verify_fail_total",
    "Total verification failures by reason code",
    ["reason"],
)

floodwait_seconds_hist = Histogram(
    "floodwait_seconds_hist",
    "Distribution of FloodWait durations from Telegram",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)

active_verifications = Gauge(
    "active_verifications",
    "Number of currently running verify tasks (leases held)",
)

verify_lease_acquired_total = Counter(
    "verify_lease_acquired_total",
    "Total verify leases successfully acquired",
)

verify_lease_rejected_total = Counter(
    "verify_lease_rejected_total",
    "Total verify lease acquisition rejections (already running)",
)

proxy_marked_unhealthy_total = Counter(
    "proxy_marked_unhealthy_total",
    "Total proxies marked unhealthy during verification",
)
