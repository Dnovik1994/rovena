"""Celery tasks for Telegram account authentication flow — barrel module.

All task implementations have been extracted into dedicated sub-modules.
This module re-exports every public name so that existing imports
(``from app.workers.tg_auth_tasks import …``) keep working.
"""

# ─── helpers (re-exported for backward compat) ───────────────────────
from app.workers.tg_auth_helpers import (  # noqa: F401
    _PRE_AUTH_DIR,
    _broadcast_account_update,
    _broadcast_flow_update,
    _cleanup_pre_auth_session,
    _ensure_pre_auth_dir,
    _extract_migrate_dc,
    _get_dc_id,
    _handle_floodwait,
    _is_dc_migrate_error,
    _is_network_error,
    _log_client_fingerprint,
    _mark_proxy_unhealthy,
    _mask_phone,
    _pre_auth_session_name,
    _pre_auth_session_path,
    _read_session_auth_key,
    _sanitize_error,
    _set_dc_id,
)

# ─── legacy send_code / confirm_code (moved to tg_auth_legacy_tasks.py) ──
from app.workers.tg_auth_legacy_tasks import (  # noqa: F401
    _run_send_code,
    send_code_task,
    _run_confirm_code,
    confirm_code_task,
)

# ─── unified_auth (moved to tg_auth_unified_tasks.py) ────────────────
from app.workers.tg_auth_unified_tasks import (  # noqa: F401
    _run_unified_auth,
    unified_auth_task,
)

# ─── confirm_password (moved to tg_auth_password_tasks.py) ──────────
from app.workers.tg_auth_password_tasks import (  # noqa: F401
    _run_confirm_password,
    confirm_password_task,
)

# ─── verify_account (moved to tg_auth_verify_tasks.py) ──────────────
from app.workers.tg_auth_verify_tasks import (  # noqa: F401
    _run_verify_account,
    verify_account_task,
)
