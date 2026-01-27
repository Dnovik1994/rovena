from pathlib import Path


def test_offline_banner_present():
    content = Path("frontend/src/components/AppShell.tsx").read_text()
    assert "Offline mode" in content
