from __future__ import annotations

from pathlib import Path


def test_worker_non_root_dockerfile():
    dockerfile = Path(__file__).resolve().parents[2] / "backend" / "Dockerfile"
    contents = dockerfile.read_text(encoding="utf-8")

    assert "adduser --disabled-password" in contents
    assert "chown -R appuser /app" in contents
    assert "USER appuser" in contents
