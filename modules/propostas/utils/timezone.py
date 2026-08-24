"""Timezone helpers used across the project."""

from __future__ import annotations

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_OFFSET = timezone(timedelta(hours=-3))
TZ_NAME = "America/Sao_Paulo"


def get_local_timezone():
    """Return the preferred local timezone.

    Tries to load the named timezone using the system tzdata database.  When
    the zoneinfo package cannot locate the entry (common on bare Windows
    environments without the ``tzdata`` package), fall back to a fixed
    UTC-3 offset so timestamp formatting continues to work.
    """

    try:
        return ZoneInfo(TZ_NAME)
    except ZoneInfoNotFoundError:
        return DEFAULT_OFFSET
