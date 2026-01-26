import logging
from pathlib import Path
from typing import Iterable

from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.models.proxy import Proxy

logger = logging.getLogger(__name__)
settings = get_settings()


def _format_proxy_line(proxy: Proxy) -> str:
    listen_port = settings.proxy_base_port + proxy.id
    command = "proxy" if proxy.type == "http" else "socks"
    if proxy.type != "http" and proxy.login and proxy.password:
        command = "textsocks"

    auth_fragment = ""
    if proxy.login and proxy.password:
        auth_fragment = f" -a{proxy.login}:{proxy.password}"

    return f"{command} -p{listen_port} -i0.0.0.0 -e{proxy.host}:{proxy.port}{auth_fragment}"


def generate_3proxy_config(proxies: Iterable[Proxy]) -> str:
    header = [
        "daemon",
        "maxconn 1000",
        "nscache 65536",
        "timeouts 1 5 30 60 180 1800 15 60",
    ]
    lines: list[str] = header
    for proxy in proxies:
        lines.append(_format_proxy_line(proxy))
    return "\n".join(lines) + "\n"


def sync_3proxy() -> None:
    config_path = Path(settings.proxy_config_path)
    with SessionLocal() as db:
        proxies = db.query(Proxy).order_by(Proxy.id.asc()).all()

    content = generate_3proxy_config(proxies)
    config_path.write_text(content, encoding="utf-8")
    logger.info("3proxy config updated", extra={"count": len(proxies)})

    if settings.proxy_reload_cmd:
        import subprocess

        subprocess.check_call(settings.proxy_reload_cmd, shell=True)
