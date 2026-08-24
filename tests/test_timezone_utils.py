import modules.propostas.utils.timezone as _tz_impl
from utils import timezone as tz


def test_get_local_timezone_uses_zoneinfo(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(_tz_impl, "ZoneInfo", lambda name: sentinel)
    assert _tz_impl.get_local_timezone() is sentinel


def test_get_local_timezone_fallback(monkeypatch):
    def raiser(_):
        raise _tz_impl.ZoneInfoNotFoundError

    monkeypatch.setattr(_tz_impl, "ZoneInfo", raiser)
    assert _tz_impl.get_local_timezone() is _tz_impl.DEFAULT_OFFSET
