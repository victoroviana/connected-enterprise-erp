"""Helpers to select themed UI campaigns based on the current date."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import os
import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = PROJECT_ROOT / "data" / "ui_campaigns.json"
HOLIDAY_CACHE_DIR = PROJECT_ROOT / "data" / "cache"
HOLIDAY_API_URL = "https://brasilapi.com.br/api/feriados/v1/{year}"
INVERTEXTO_TOKEN = os.getenv("INVERTEXTO_TOKEN", "").strip()
INVERTEXTO_STATES: tuple[str, ...] = ("RJ", "SP", "PR", "ES")
CACHE_MAX_AGE_DAYS = 45
LEVEL_PRIORITIES = {
    "nacional": 400,
    "national": 400,
    "estadual": 300,
    "state": 300,
    "municipal": 250,
    "city": 250,
    "municipio": 250,
    "facultativo": 220,
    "optional": 220,
}


def _holiday_style(name: str) -> dict[str, Any]:
    lower = name.lower()
    styles = [
        (
            lambda n: "natal" in n,
            {
                "colors": {
                    "hero_start": "#166534",
                    "hero_end": "#b91c1c",
                    "hero_text": "#fef2f2",
                    "badge_bg": "rgba(255,255,255,0.9)",
                    "badge_text": "#b91c1c",
                },
                "message": "Feliz Natal! Que a celebra\u00e7\u00e3o traga aconchego e opera\u00e7\u00f5es confi\u00e1veis para todo o time.",
                "badge": "Feliz Natal",
                "title": "Feliz Natal",
            },
        ),
        (
            lambda n: "ano novo" in n or "confraterniza" in n,
            {
                "colors": {
                    "hero_start": "#ffffff",
                    "hero_end": "#facc15",
                    "hero_text": "#1f2937",
                    "badge_bg": "rgba(255,255,255,0.96)",
                    "badge_text": "#854d0e",
                },
                "message": "Pr\u00f3spero Ano Novo! Seguimos juntos conectando pessoas e resultados.",
                "badge": "Ano Novo",
                "title": "Boas-vindas ao novo ciclo",
            },
        ),
        (
            lambda n: "independ" in n,
            {
                "colors": {
                    "hero_start": "#047857",
                    "hero_end": "#facc15",
                    "hero_text": "#0f172a",
                    "badge_bg": "rgba(248,250,252,0.95)",
                    "badge_text": "#0f172a",
                },
                "message": "Dia da Independ\u00eancia: celebramos nossa hist\u00f3ria e refor\u00e7amos o compromisso com solu\u00e7\u00f5es nacionais.",
                "badge": "Independ\u00eancia do Brasil",
                "title": "7 de Setembro",
            },
        ),
        (
            lambda n: "tiradentes" in n,
            {
                "colors": {
                    "hero_start": "#fbbf24",
                    "hero_end": "#b45309",
                    "hero_text": "#1f2937",
                    "badge_bg": "rgba(255,248,220,0.92)",
                    "badge_text": "#92400e",
                },
                "message": "Tiradentes: lembramos coragem e integridade para seguir construindo confian\u00e7a.",
                "badge": "Dia de Tiradentes",
                "title": "Mem\u00f3ria e Liberdade",
            },
        ),
        (
            lambda n: "finados" in n,
            {
                "colors": {
                    "hero_start": "#334155",
                    "hero_end": "#0f172a",
                    "hero_text": "#e2e8f0",
                    "badge_bg": "rgba(226,232,240,0.28)",
                    "badge_text": "#f8fafc",
                },
                "message": "Dia de Finados: momento de respeito, lembran\u00e7as e gratid\u00e3o.",
                "badge": "Finados",
                "title": "Mem\u00f3ria e respeito",
            },
        ),
        (
            lambda n: "carnaval" in n,
            {
                "colors": {
                    "hero_start": "#db2777",
                    "hero_end": "#7c3aed",
                    "hero_text": "#fdf4ff",
                    "badge_bg": "rgba(253,244,255,0.85)",
                    "badge_text": "#6d28d9",
                },
                "message": "Carnaval: celebre com alegria e mantenha suas opera\u00e7\u00f5es organizadas mesmo no ritmo da festa.",
                "badge": "Carnaval",
                "title": "Carnaval conectado",
            },
        ),
        (
            lambda n: "pscoa" in n or "pascoa" in n,
            {
                "colors": {
                    "hero_start": "#7c3aed",
                    "hero_end": "#ec4899",
                    "hero_text": "#fdf4ff",
                    "badge_bg": "rgba(250,240,255,0.9)",
                    "badge_text": "#6d28d9",
                },
                "message": "P\u00e1scoa: tempo de renova\u00e7\u00e3o. Conte com a Sollus para manter suas solu\u00e7\u00f5es integradas.",
                "badge": "P\u00e1scoa",
                "title": "Renova\u00e7\u00e3o e conex\u00e3o",
            },
        ),
        (
            lambda n: "corpus christi" in n,
            {
                "colors": {
                    "hero_start": "#fbbf24",
                    "hero_end": "#7c3aed",
                    "hero_text": "#f8fafc",
                    "badge_bg": "rgba(248,250,252,0.9)",
                    "badge_text": "#6d28d9",
                },
                "message": "Corpus Christi: que o feriado traga serenidade e planejamento para a equipe.",
                "badge": "Corpus Christi",
                "title": "Corpus Christi",
            },
        ),
        (
            lambda n: "conscincia negra" in n or "consciencia negra" in n,
            {
                "colors": {
                    "hero_start": "#7f1d1d",
                    "hero_end": "#0f172a",
                    "hero_text": "#fef2f2",
                    "badge_bg": "rgba(127,29,29,0.18)",
                    "badge_text": "#f1f5f9",
                },
                "message": "Dia da Consci\u00eancia Negra: fortalecemos a diversidade e o respeito no ambiente corporativo.",
                "badge": "Consci\u00eancia Negra",
                "title": "Diversidade e respeito",
            },
        ),
    ]

    for matcher, style in styles:
        if matcher(lower):
            return style

    return {
        "colors": {
            "hero_start": "#047857",
            "hero_end": "#1d4ed8",
            "hero_text": "#f8fafc",
            "badge_bg": "rgba(248,250,252,0.92)",
            "badge_text": "#0f172a",
        }
    }
DEFAULT_THEME_ID = "default"


@lru_cache(maxsize=1)
def _load_calendar() -> list[dict[str, Any]]:
    """Load and cache the UI calendar definitions from disk."""
    if not CALENDAR_PATH.exists():
        return []
    with CALENDAR_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Highest priority first, fallback to order of file otherwise
    return sorted(data, key=lambda item: int(item.get("priority", 100)), reverse=True)


def _holiday_cache_path(year: int) -> Path:
    HOLIDAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return HOLIDAY_CACHE_DIR / f"feriados_{year}.json"


def _invertexto_cache_path(year: int, state: str | None) -> Path:
    HOLIDAY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    label = (state or "br").lower()
    return HOLIDAY_CACHE_DIR / f"invertexto_{year}_{label}.json"


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.utcnow() - datetime.utcfromtimestamp(path.stat().st_mtime)
    return age <= timedelta(days=CACHE_MAX_AGE_DAYS)


@lru_cache(maxsize=6)
def _fetch_brasil_api_holidays(year: int) -> list[dict[str, Any]]:
    url = HOLIDAY_API_URL.format(year=year)
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        cache_path = _holiday_cache_path(year)
        cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data if isinstance(data, list) else []
    except Exception:
        cache_path = _holiday_cache_path(year)
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    return cached
            except Exception:
                return []
        return []


def _fetch_invertexto_holidays(year: int, state: str | None) -> list[dict[str, Any]]:
    if not INVERTEXTO_TOKEN:
        return []
    cache_path = _invertexto_cache_path(year, state)
    # Use cache if still fresh
    if _cache_is_fresh(cache_path):
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, list):
                return cached
        except Exception:
            pass

    params = {"token": INVERTEXTO_TOKEN}
    if state:
        params["state"] = state.upper()

    try:
        response = requests.get(
            f"https://api.invertexto.com/v1/holidays/{year}",
            params=params,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
    except Exception:
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    return cached
            except Exception:
                pass
    return []


def _collect_holiday_entries(year: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    brasil_entries = _fetch_brasil_api_holidays(year)
    entries.extend({**item, "_source": "brasilapi"} for item in brasil_entries if isinstance(item, dict))

    if INVERTEXTO_TOKEN:
        entries.extend({**item, "_source": "invertexto", "_state": None}
                       for item in _fetch_invertexto_holidays(year, None))
        for uf in INVERTEXTO_STATES:
            entries.extend({**item, "_source": "invertexto", "_state": uf}
                           for item in _fetch_invertexto_holidays(year, uf))

    return entries


def _build_dynamic_holidays(year: int, existing_dates: set[str]) -> List[dict[str, Any]]:
    holidays = _collect_holiday_entries(year)
    themes: List[dict[str, Any]] = []
    best_by_date: dict[str, dict[str, Any]] = {}

    for item in holidays:
        if not isinstance(item, dict):
            continue
        date_str = item.get("date")
        name = (item.get("fullName") or item.get("name") or "Feriado Nacional").strip()
        level = (item.get("level") or item.get("holiday_type") or "nacional").lower()
        htype = (item.get("type") or "feriado").lower()
        if not date_str or date_str in existing_dates:
            continue
        style_info = _holiday_style(name)
        colors = style_info.get("colors")
        if not colors:
            colors = {
                "hero_start": "#047857",
                "hero_end": "#1d4ed8",
                "hero_text": "#f8fafc",
                "badge_bg": "rgba(248,250,252,0.92)",
                "badge_text": "#065f46",
            }

        state = item.get("state") or item.get("_state")
        city = item.get("city")

        location_msg = "em todo o pa\u00eds"
        if level.startswith("estadua") and state:
            location_msg = f"no estado de {state.upper()}"
        elif city:
            location_msg = f"em {city.title()}"

        custom_message = style_info.get("message")
        if custom_message:
            if "{location}" in custom_message:
                message = custom_message.format(location=location_msg)
            else:
                message = custom_message
        else:
            message = (
                f"Hoje celebramos {name} {location_msg}. Conte com a Sollus para manter suas opera\u00e7\u00f5es conectadas e seguras."  # noqa: E501
            )

        badge_text = style_info.get("badge") or name
        title_text = style_info.get("title") or name

        priority = LEVEL_PRIORITIES.get(level, 220)
        source_priority = 2 if item.get("_source") == "invertexto" else 1

        theme = {
            "id": f"holiday-{date_str}-{source_priority}",
            "type": "holiday",
            "priority": priority,
            "date": date_str,
                "label": name,
                "badge": badge_text,
                "title": title_text,
            "message": message,
            "colors": colors,
            "raw": item,
            "holiday_type": level,
            "source": item.get("_source", "brasilapi"),
            "state": state,
            "city": city,
        }

        current = best_by_date.get(date_str)
        if current is None or priority > current.get("priority", 0) or (
            priority == current.get("priority", 0)
            and source_priority > current.get("_source_priority", 0)
        ):
            theme["_source_priority"] = source_priority
            best_by_date[date_str] = theme

    holiday_themes = list(best_by_date.values())
    _extend_holiday_week_windows(holiday_themes)
    for theme in holiday_themes:
        theme.pop("_source_priority", None)
    themes.extend(holiday_themes)
    return themes



def _extend_holiday_week_windows(themes: list[dict[str, Any]]) -> None:
    """Allow holiday themes to stay active from the week's Monday until the holiday."""

    buckets: dict[tuple[int, int], list[tuple[dict[str, Any], date]]] = defaultdict(list)

    for theme in themes:
        if theme.get("type") != "holiday":
            continue
        date_str = theme.get("date")
        if not date_str or len(date_str) != 10:
            continue
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        iso_year, iso_week, _ = target_date.isocalendar()
        buckets[(iso_year, iso_week)].append((theme, target_date))

    for entries in buckets.values():
        entries.sort(key=lambda pair: pair[1])
        if not entries:
            continue

        first_date = entries[0][1]
        week_start = first_date - timedelta(days=first_date.weekday())

        for idx, (theme, target_date) in enumerate(entries):
            if idx == 0:
                start_date = week_start
            else:
                prev_target = entries[idx - 1][1]
                start_date = prev_target + timedelta(days=1)

            if start_date < week_start:
                start_date = week_start
            if start_date > target_date:
                start_date = target_date

            theme["start"] = start_date.isoformat()
            theme["end"] = target_date.isoformat()


def _md_value(value: str) -> int:
    """Return an integer MMDD representation for comparisons."""
    value = value.strip()
    if len(value) == 10 and value.count("-") == 2:  # YYYY-MM-DD
        _, month, day = value.split("-")
    else:  # assume MM-DD
        month, day = value.split("-")
    return int(month) * 100 + int(day)


def _matches_single_day(theme: dict[str, Any], today: date) -> bool:
    target = theme.get("date")
    if not target:
        return False
    if len(target) == 10 and target.count("-") == 2:
        return today.isoformat() == target
    return _md_value(target) == today.month * 100 + today.day


def _matches_range(theme: dict[str, Any], today: date) -> bool:
    start = theme.get("start")
    end = theme.get("end")
    if not start or not end:
        return False
    start_md = _md_value(str(start))
    end_md = _md_value(str(end))
    today_md = today.month * 100 + today.day
    if start_md <= end_md:
        return start_md <= today_md <= end_md
    # Range crossing the year boundary (e.g. 12-15 to 01-05)
    return today_md >= start_md or today_md <= end_md


def _is_theme_active(theme: dict[str, Any], today: date) -> bool:
    if _matches_single_day(theme, today):
        return True
    if _matches_range(theme, today):
        return True
    return False


def _find_default_theme(themes: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for theme in themes:
        if theme.get("id") == DEFAULT_THEME_ID or theme.get("type") == "default":
            return theme
    return None


def get_active_theme(today: date | None = None) -> Dict[str, Any]:
    """Return the theme dict currently active for the given date."""
    today = today or date.today()
    themes = _load_calendar()
    existing_dates = {theme.get("date") for theme in themes if theme.get("date")}
    themes.extend(_build_dynamic_holidays(today.year, existing_dates))
    themes = sorted(themes, key=lambda item: int(item.get("priority", 100)), reverse=True)
    default_theme = _find_default_theme(themes) or {
        "id": DEFAULT_THEME_ID,
        "badge": "Plataforma integrada",
        "title": "Bem-vindo ao Sollus Connected",
        "message": "Centralizamos solu\u00e7\u00f5es Sollus em uma \u00fanica experi\u00eancia.",
        "colors": {
            "hero_start": "#0B3B8C",
            "hero_end": "#0E5DC6",
            "hero_text": "#E9F2FF",
            "badge_bg": "rgba(255,255,255,0.16)",
            "badge_text": "#0B3B8C",
        },
        "illustration": "images/sol.gif",
    }

    for theme in themes:
        if _is_theme_active(theme, today):
            return theme

    return default_theme


__all__ = ["get_active_theme"]

