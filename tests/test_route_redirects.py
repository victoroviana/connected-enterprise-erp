from app import create_app


def _make_client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_root_redirects_to_login_when_anonymous():
    client = _make_client()
    response = client.get("/", headers={"Accept": "text/html"})
    assert response.status_code == 302
    assert "/auth/login" in response.headers.get("Location", "")


def test_tickets_dashboard_redirects_to_login_when_anonymous():
    client = _make_client()
    response = client.get("/tickets/dashboard", headers={"Accept": "text/html"})
    assert response.status_code == 302
    location = response.headers.get("Location", "")
    assert "/auth/login" in location
    # Suporta tanto a versão literal quanto a URL-encoded
    assert ("next=/tickets/dashboard" in location or "next=%2Ftickets%2Fdashboard" in location)
