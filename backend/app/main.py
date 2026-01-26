import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import sentry_sdk
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

configure_logging()

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
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_ctx_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    request_id_ctx_var.reset(token)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
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


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    with SessionLocal() as db:
        total = db.query(Account).count()
        accounts_total.set(total)
        for status in AccountStatus:
            count = db.query(Account).filter(Account.status == status).count()
            accounts_by_status.labels(status=status.value).set(count)

    try:
        from redis import Redis

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
