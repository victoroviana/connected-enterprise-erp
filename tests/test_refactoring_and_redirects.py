import pytest
from app import create_app
from flask import Flask, request
from utils.helpers import wants_json, normalize_dept_name, paginate, format_date, format_datetime
from datetime import date, datetime

def test_helpers_wants_json():
    app = Flask(__name__)
    with app.test_request_context(headers={"X-Requested-With": "XMLHttpRequest"}):
        assert wants_json() is True
    with app.test_request_context(headers={"Accept": "application/json"}):
        assert wants_json() is True
    with app.test_request_context(headers={"Accept": "text/html"}):
        assert wants_json() is False

def test_helpers_normalize_dept_name():
    assert normalize_dept_name("Depósito de Equipamentos") == "DEPOSITO DE EQUIPAMENTOS"
    assert normalize_dept_name("  Contratos  ") == "CONTRATOS"
    assert normalize_dept_name(None) == ""

def test_helpers_paginate():
    res = paginate(100, 2, 10)
    assert res["page"] == 2
    assert res["pages"] == 10
    assert res["total"] == 100
    assert res["has_prev"] is True
    assert res["prev_num"] == 1
    assert res["has_next"] is True
    assert res["next_num"] == 3

    # Boundaries
    res_first = paginate(100, 1, 10)
    assert res_first["has_prev"] is False
    assert res_first["has_next"] is True

    res_last = paginate(100, 10, 10)
    assert res_last["has_prev"] is True
    assert res_last["has_next"] is False

def test_helpers_format_date():
    assert format_date(date(2026, 6, 10)) == "10/06/2026"
    assert format_date(datetime(2026, 6, 10, 15, 30)) == "10/06/2026"
    assert format_date("2026-06-10") == "10/06/2026"
    assert format_date("10/06/2026") == "10/06/2026"
    assert format_date("0000-00-00") == ""
    assert format_date(None) == ""
    assert format_date("invalid-date-string") == "invalid-date-string"

def test_helpers_format_datetime():
    assert format_datetime(datetime(2026, 6, 10, 15, 30, 22)) == "10/06/2026 15:30:22"
    assert format_datetime("2026-06-10 15:30:22") == "10/06/2026 15:30:22"
    assert format_datetime("10/06/2026 15:30:22") == "10/06/2026 15:30:22"
    assert format_datetime("0000-00-00 00:00:00") == ""
    assert format_datetime(None) == ""
    assert format_datetime("invalid-datetime-string") == "invalid-datetime-string"

def test_open_redirect_on_login():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    
    from modules.propostas.blueprints.auth.login import _is_safe_url
    with app.test_request_context():
        assert _is_safe_url("/contratos") is True
        assert _is_safe_url("http://evil.com") is False
        assert _is_safe_url("//evil.com") is False

def test_cracha_download_routes_require_authentication():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    client = app.test_client()

    # Try downloading recibo file or cracha file without login should redirect or deny
    r1 = client.get("/cracha/recibos/arquivo/test.pdf")
    assert r1.status_code in (302, 401)
    
    r2 = client.get("/cracha/crachas/arquivo/test.png")
    assert r2.status_code in (302, 401)
