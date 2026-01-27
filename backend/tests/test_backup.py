from pathlib import Path


def test_backup_crontab_configured():
    root = Path(__file__).resolve().parents[2]
    crontab = root / "crontab.txt"
    compose = root / "docker-compose.prod.yml"

    assert crontab.exists()
    crontab_content = crontab.read_text(encoding="utf-8")
    assert "pg_dump" in crontab_content
    assert "redis-dump" in crontab_content

    compose_content = compose.read_text(encoding="utf-8")
    assert "cron:" in compose_content
    assert "backups:" in compose_content
