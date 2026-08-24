import pytest

from utils.systems import (
    DEFAULT_SYSTEM_OPTIONS,
    iter_system_options,
    get_system_option,
    build_system_item,
    serialize_system_payload,
    parse_unit_price,
)


def test_system_options_catalog_contains_expected_keys():
    keys = {opt.key for opt in DEFAULT_SYSTEM_OPTIONS.values()}
    assert {"rhid", "sollus_access", "velti_ponto", "henry_ponto", "secullum"}.issubset(keys)


def test_iter_system_options_returns_defaults_without_overrides():
    keys = {opt.key for opt in iter_system_options()}
    assert {"rhid", "sollus_access", "velti_ponto", "henry_ponto", "secullum"}.issubset(keys)


def test_build_system_item_uses_overrides():
    option = get_system_option("rhid")
    item = build_system_item(option, quantity=5, unit_price=123.45)
    assert item.quantity == 5
    assert item.unit_price == 123.45
    assert option.label in item.name


def test_serialize_system_payload_round_trips():
    option = get_system_option("velti_ponto")
    payload = serialize_system_payload(option, 3, 99.9)
    assert payload["key"] == option.key
    assert payload["quantity"] == 3
    assert payload["unit_price"] == pytest.approx(99.9)


def test_parse_unit_price_handles_br_formats():
    assert parse_unit_price("1.234,56") == 1234.56
    assert parse_unit_price("R$ 250,00") == 250.0
    assert parse_unit_price("") == 0.0


def test_build_system_item_honors_total_override():
    option = get_system_option("rhid")
    item = build_system_item(option, quantity=2, unit_price=50.0, total_price=999.0)
    assert item.total_override == 999.0