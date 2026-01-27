def test_app_import() -> None:
    from app.main import app

    assert app is not None
