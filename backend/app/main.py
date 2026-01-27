import subprocess
import uuid

from exceptiongroup import ExceptionGroup
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
import sentry_sdk
from redis import Redis
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
import stripe

from app.api.v1 import router as api_router
from app.core.logging import configure_logging, request_id_ctx_var
from app.core.rate_limit import limiter
from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.services.websocket_manager import manager
from app.core.database import SessionLocal
from app.models.account import Account, AccountStatus
from app.models.user import User
from app.core.metrics import accounts_by_status, accounts_total, celery_queue_length

settings = get_settings()
logger = logging.getLogger(__name__)
APP_VERSION = "1.0.0"

configure_logging(production=settings.production)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=1.0,
        integrations=[FastApiIntegration(), CeleryIntegration()],
    )

app = FastAPI(title=settings.app_name)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)


async def _internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", extra={"path": str(request.url.path)})
    sentry_sdk.capture_exception(exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"type": "internal_error"},
        )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "500", "message": "Internal error"}},
    )


class ExceptionGroupMiddleware:
    def __init__(self, app_instance: FastAPI):
        self.app = app_instance

    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        except ExceptionGroup as exc:
            if scope.get("type") != "http":
                raise
            request = Request(scope, receive=receive)
            response = await _internal_error_response(request, exc)
            await response(scope, receive, send)
        except Exception as exc:
            if scope.get("type") != "http":
                raise
            if isinstance(
                exc,
                (
                    HTTPException,
                    StarletteHTTPException,
                    RequestValidationError,
                    RateLimitExceeded,
                ),
            ):
                raise
            request = Request(scope, receive=receive)
            response = await _internal_error_response(request, exc)
            await response(scope, receive, send)


@app.on_event("startup")
async def on_startup() -> None:
    commit = _get_git_commit()
    logger.info(
        "App starting | version=%s | commit=%s | env=PRODUCTION=%s",
        APP_VERSION,
        commit,
        settings.production,
    )
    try:
        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
        logger.info("Redis connected")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis connection failed", extra={"error": str(exc)})


class RequestIdMiddleware:
    def __init__(self, app_instance: FastAPI):
        self.app = app_instance

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx_var.set(request_id)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                mutable["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx_var.reset(token)


class SecurityHeadersMiddleware:
    def __init__(self, app_instance: FastAPI):
        self.app = app_instance

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                csp = "default-src 'self'; frame-ancestors 'self'; base-uri 'self';"
                if settings.production:
                    csp = f"{csp} upgrade-insecure-requests;"
                mutable["X-Content-Type-Options"] = "nosniff"
                mutable["X-XSS-Protection"] = "1; mode=block"
                mutable["Content-Security-Policy"] = csp
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ExceptionGroupMiddleware)




@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": exc.detail}},
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "404", "message": "Not found"}},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": str(exc.status_code), "message": exc.detail}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "422", "message": "Validation error"}},
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "429", "message": "Rate limit exceeded"}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return await _internal_error_response(request, exc)


@app.exception_handler(ExceptionGroup)
async def unhandled_exception_group_handler(
    request: Request, exc: ExceptionGroup
) -> JSONResponse:
    return await _internal_error_response(request, exc)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


@app.get("/version")
async def version() -> dict[str, str]:
    return {"version": APP_VERSION, "commit": _get_git_commit()}


@app.get("/metrics")
async def metrics() -> Response:
    with SessionLocal() as db:
        total = db.query(Account).count()
        accounts_total.set(total)
        for status in AccountStatus:
            count = db.query(Account).filter(Account.status == status).count()
            accounts_by_status.labels(status=status.value).set(count)

    try:
        redis_client = Redis.from_url(settings.redis_url)
        celery_queue_length.set(redis_client.llen("celery"))
    except Exception:  # noqa: BLE001
        celery_queue_length.set(0)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request) -> dict[str, str]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe webhook secret is not configured",
        )

    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=settings.stripe_webhook_secret,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        tariff_id = metadata.get("tariff_id")
        if user_id and tariff_id:
            with SessionLocal() as db:
                user = db.get(User, int(user_id))
                if user:
                    user.tariff_id = int(tariff_id)
                    db.commit()

    return {"status": "ok"}


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub", 0))
    except Exception:  # noqa: BLE001
        await websocket.close(code=1008)
        return

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=1008)
            return

    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
