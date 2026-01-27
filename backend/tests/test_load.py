from pathlib import Path


def test_locustfile_smoke():
    root = Path(__file__).resolve().parents[2]
    locustfile = root / "locustfile.py"
    assert locustfile.exists()
    content = locustfile.read_text(encoding="utf-8")
    assert "class ApiUser" in content
    assert "/api/v1/auth/telegram" in content
