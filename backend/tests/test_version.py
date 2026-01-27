def test_version_endpoint(client):
    response = client.get("/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "1.0.0"
    assert "commit" in payload
