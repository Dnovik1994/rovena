from slowapi import Limiter


def _rate_limit_key(request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return "anonymous"


def tariff_rate_limit(request) -> str:
    user = getattr(request.state, "user", None)
    max_invites = 50
    if user and getattr(user, "tariff", None):
        max_invites = user.tariff.max_invites_day
    return f"{max_invites}/day"

limiter = Limiter(key_func=_rate_limit_key)
