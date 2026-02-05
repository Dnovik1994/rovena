import logging
import socket

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.rbac import require_permission
from app.core.database import get_db
from app.models.proxy import Proxy
from app.schemas.proxy import ProxyCreate, ProxyResponse, ProxyUpdate
from app.clients.telegram_client import TelegramClientDisabledError
from app.services.proxy_validation import validate_proxy
from app.workers.tasks import sync_3proxy_config, validate_proxy_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxies"])


@router.get("/proxies", response_model=list[ProxyResponse])
async def list_proxies(
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("proxies", "list")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ProxyResponse]:
    proxies = db.query(Proxy).order_by(Proxy.created_at.desc()).offset(offset).limit(limit).all()
    return [ProxyResponse.model_validate(proxy) for proxy in proxies]


@router.post("/proxies", response_model=ProxyResponse, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    payload: ProxyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("proxies", "create")),
) -> ProxyResponse:
    proxy = Proxy(
        host=payload.host,
        port=payload.port,
        login=payload.login,
        password=payload.password,
        type=payload.type,
        country=payload.country,
    )
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    sync_3proxy_config.delay()
    validate_proxy_task.delay(proxy.id)
    return ProxyResponse.model_validate(proxy)


@router.patch("/proxies/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: int,
    payload: ProxyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("proxies", "update")),
) -> ProxyResponse:
    proxy = db.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")

    _PROXY_UPDATE_FIELDS = {
        "host", "port", "login", "password", "type", "country",
        "status", "uptime_seconds", "latency_ms",
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field not in _PROXY_UPDATE_FIELDS:
            continue
        setattr(proxy, field, value)

    db.commit()
    db.refresh(proxy)
    sync_3proxy_config.delay()
    validate_proxy_task.delay(proxy.id)
    return ProxyResponse.model_validate(proxy)


@router.delete("/proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("proxies", "delete")),
) -> None:
    proxy = db.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    db.delete(proxy)
    db.commit()
    sync_3proxy_config.delay()
    return None


@router.post("/proxies/validate")
async def validate_proxy_credentials(
    payload: ProxyCreate,
    current_user=Depends(require_permission("proxies", "validate")),
) -> dict[str, object]:
    """Validate proxy connectivity by attempting a TCP connection."""
    try:
        sock = socket.create_connection(
            (payload.host, payload.port), timeout=5
        )
        sock.close()
        return {"valid": True, "error": None}
    except (socket.timeout, OSError) as exc:
        logger.info(
            "Proxy validation failed",
            extra={"host": payload.host, "port": payload.port, "error": str(exc)},
        )
        return {"valid": False, "error": "Connection failed"}


@router.post("/proxies/{proxy_id}/validate", response_model=ProxyResponse)
async def validate_proxy_by_id(
    proxy_id: int,
    current_user=Depends(require_permission("proxies", "validate")),
) -> ProxyResponse:
    try:
        proxy = await validate_proxy(proxy_id)
    except TelegramClientDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Telegram client disabled",
        ) from exc
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    return ProxyResponse.model_validate(proxy)
