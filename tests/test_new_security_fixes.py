import pytest
from app import create_app
from modules.contratos.blueprints.contratos import _next_id


def _make_client():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app.test_client()


def test_404_error_page_html():
    client = _make_client()
    response = client.get("/non-existent-route-for-testing", headers={"Accept": "text/html"})
    assert response.status_code == 404
    html_content = response.data.decode("utf-8")
    assert "Página não encontrada" in html_content


def test_404_error_page_json():
    client = _make_client()
    response = client.get(
        "/non-existent-route-for-testing",
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    )
    assert response.status_code == 404
    data = response.get_json()
    assert data is not None
    assert data["ok"] is False
    assert data["message"] == "Página não encontrada."


def test_next_id_invalid_table_raises_value_error():
    with pytest.raises(ValueError, match="Invalid table or column name in _next_id"):
        _next_id("unsafe_table_name")


def test_next_id_invalid_column_raises_value_error():
    with pytest.raises(ValueError, match="Invalid table or column name in _next_id"):
        _next_id("ja_fin_contas_a_receber_contratos", "unsafe_column_name")
