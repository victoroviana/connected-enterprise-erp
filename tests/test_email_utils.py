import pytest

from blueprints.propostas.propostas import _parse_emails_list


def test_parse_emails_accepts_multiple_separators():
    raw = "cliente@empresa.com, suporte@empresa.com;financeiro@empresa.com\n vendas@empresa.com "
    result = _parse_emails_list(raw)
    assert result == [
        "cliente@empresa.com",
        "suporte@empresa.com",
        "financeiro@empresa.com",
        "vendas@empresa.com",
    ]


def test_parse_emails_ignores_empty_tokens():
    assert _parse_emails_list("\n , ; ") == []


def test_parse_emails_rejects_invalid_addresses():
    with pytest.raises(ValueError):
        _parse_emails_list("clienteempresa.com")
