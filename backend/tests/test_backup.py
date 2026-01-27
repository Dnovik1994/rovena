from pathlib import Path


def test_backup_crontab_entries_present():
    crontab = Path("crontab.txt").read_text()
    assert "mysqldump -h db" in crontab
    assert "redis-cli -u ${REDIS_URL}" in crontab
    assert "find /backups -name \"db-*.sql.gz\" -mtime +7 -delete" in crontab
    assert "find /backups -name \"redis-*.rdb.gz\" -mtime +7 -delete" in crontab
