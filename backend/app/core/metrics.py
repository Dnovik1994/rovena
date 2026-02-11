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
