def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "accounts_total" in body
    assert "accounts_by_status" in body
    assert "campaign_invites_success_total" in body
    assert "campaign_invites_errors_total" in body
