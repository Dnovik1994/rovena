from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_offline_banner_present():
    content = (REPO_ROOT / "frontend/src/components/AppShell.tsx").read_text()
    assert "Offline mode" in content
