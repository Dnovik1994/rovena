def test_security_headers_present(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Content-Security-Policy" in response.headers


def test_csp_allows_telegram_frame_ancestors(client):
    """CSP must allow Telegram WebApp to embed the app in an iframe."""
    response = client.get("/health")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors" in csp
    assert "https://web.telegram.org" in csp
    assert "https://t.me" in csp
