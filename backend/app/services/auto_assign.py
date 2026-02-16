"""Auto-assignment logic for API apps to Telegram accounts."""

import logging

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.telegram_account import TelegramAccount
from app.models.telegram_api_app import TelegramApiApp

logger = logging.getLogger(__name__)


class NoAvailableApiAppError(Exception):
    """Raised when no suitable API app can be assigned."""


def assign_api_app(account: TelegramAccount, db: Session) -> TelegramApiApp:
    """Pick the least-loaded active API app and assign it to *account*.

    Selection rules
    ----------------
    1. Only active apps (``is_active=True``).
    2. Current account count must be **< max_accounts**.
    3. Exclude apps that are used by other accounts on the **same proxy**
       (or both without a proxy) — this keeps the (api_id + IP)
       combination unique.  The ``proxy_id IS NULL`` case needs explicit
       application-level enforcement because the DB constraint
       ``UNIQUE(api_app_id, proxy_id)`` treats every NULL as distinct.
    4. Among the remaining candidates pick the one with the fewest
       linked accounts.

    The caller is responsible for committing the session.

    Raises
    ------
    NoAvailableApiAppError
        If no suitable API app is found.
    """

    # Sub-query: how many accounts reference each api_app (excluding current)
    account_counts = (
        db.query(
            TelegramAccount.api_app_id,
            func.count(TelegramAccount.id).label("cnt"),
        )
        .filter(
            TelegramAccount.api_app_id.isnot(None),
            TelegramAccount.id != account.id,
        )
        .group_by(TelegramAccount.api_app_id)
        .subquery()
    )

    # Main query: active apps with room for another account
    query = (
        db.query(TelegramApiApp, func.coalesce(account_counts.c.cnt, 0).label("cnt"))
        .outerjoin(account_counts, TelegramApiApp.id == account_counts.c.api_app_id)
        .filter(
            TelegramApiApp.is_active.is_(True),
            func.coalesce(account_counts.c.cnt, 0) < TelegramApiApp.max_accounts,
        )
    )

    # 3) Avoid api_apps that are already paired with other accounts on the
    #    same proxy (or both without a proxy).
    if account.proxy_id is not None:
        used_on_same_proxy = (
            db.query(TelegramAccount.api_app_id)
            .filter(
                TelegramAccount.proxy_id == account.proxy_id,
                TelegramAccount.api_app_id.isnot(None),
                TelegramAccount.id != account.id,
            )
            .subquery()
        )
        query = query.filter(TelegramApiApp.id.notin_(used_on_same_proxy))
    else:
        # proxy_id IS NULL: the DB UNIQUE(api_app_id, proxy_id) constraint
        # does NOT catch duplicates when proxy_id is NULL because in SQL
        # NULL != NULL.  We enforce uniqueness at the application level:
        # at most one account without a proxy per api_app.
        used_without_proxy = (
            db.query(TelegramAccount.api_app_id)
            .filter(
                TelegramAccount.proxy_id.is_(None),
                TelegramAccount.api_app_id.isnot(None),
                TelegramAccount.id != account.id,
            )
            .subquery()
        )
        query = query.filter(TelegramApiApp.id.notin_(used_without_proxy))

    # 4) Least loaded first
    result = query.order_by("cnt").first()

    if result is None:
        logger.warning(
            "event=no_available_api_app account_id=%s proxy_id=%s",
            account.id,
            account.proxy_id,
        )
        raise NoAvailableApiAppError("Нет доступных API-приложений")

    api_app: TelegramApiApp = result[0]
    account.api_app_id = api_app.id

    # Flush to trigger the UNIQUE(api_app_id, proxy_id) constraint early.
    # The application-level filter above should already prevent duplicates,
    # but a concurrent transaction could slip through without the DB check.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise NoAvailableApiAppError(
            "Комбинация API-приложения и прокси уже используется другим аккаунтом"
        )

    logger.info(
        "event=api_app_assigned account_id=%s api_app_id=%s proxy_id=%s",
        account.id,
        api_app.id,
        account.proxy_id,
    )
    return api_app
