"""Helpers to select themed UI campaigns based on the current date."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import os
import unicodedata
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


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _holiday_style(name: str) -> dict[str, Any]:
    lower = _strip_accents(name)
    styles = [
        (
            lambda n: "natal" in n,
            {
                "colors": {
                    "hero_start": "#166534",
                    "hero_end": "#b91c1c",
                    "hero_text": "#fef2f2",
                    "badge_bg": "rgba(185, 28, 28, 0.18)",
                    "badge_text": "#f87171",
                    "accent": "#b91c1c",
                },
                "message": "Feliz Natal! Que a celebração traga fortes conexões, paz e momentos especiais para toda a equipe. Nossas unidades estarão fechadas nesta data.",
                "badge": "Feliz Natal",
                "title": "Feliz Natal",
                "navbar_gif": "images/themes/natal_gorro_piscapisca.gif",
            },
        ),
        (
            lambda n: "ano novo" in n or "confraterniza" in n,
            {
                "colors": {
                    "hero_start": "#0f172a",
                    "hero_end": "#ca8a04",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(250, 204, 21, 0.18)",
                    "badge_text": "#fde047",
                    "accent": "#eab308",
                },
                "message": "Próspero Ano Novo! Um ciclo de novas conquistas e conexões de sucesso. Nossas unidades estarão fechadas nesta data.",
                "badge": "Ano Novo",
                "title": "Boas-vindas ao Novo Ano",
                "navbar_gif": "images/themes/anonovo_tacas_fogos.gif",
            },
        ),
        (
            lambda n: "aparecida" in n or "padroeira" in n,
            {
                "colors": {
                    "hero_start": "#0f172a",
                    "hero_end": "#1e3a8a",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(250, 204, 21, 0.18)",
                    "badge_text": "#facc15",
                    "accent": "#facc15",
                },
                "message": "Nossa Senhora Aparecida: padroeira do Brasil. Nossas unidades estarão fechadas nesta data em respeito ao feriado nacional.",
                "badge": "Feriado Nacional • N. Sra. Aparecida",
                "title": "Nossa Senhora Aparecida",
                "navbar_gif": "images/themes/nossa_senhora_aparecida.gif",
            },
        ),
        (
            lambda n: "independ" in n,
            {
                "colors": {
                    "hero_start": "#047857",
                    "hero_end": "#15803d",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(248,250,252,0.95)",
                    "badge_text": "#0f172a",
                    "accent": "#facc15",
                },
                "message": "Dia da Independência do Brasil: celebramos a história do nosso país. Nossas unidades estarão fechadas nesta data, retornando ao expediente normal no próximo dia útil.",
                "badge": "Independência do Brasil",
                "title": "7 de Setembro",
                "navbar_gif": "images/themes/independencia_brasil.gif",
            },
        ),
        (
            lambda n: "republica" in n or "república" in n,
            {
                "colors": {
                    "hero_start": "#047857",
                    "hero_end": "#15803d",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(248,250,252,0.95)",
                    "badge_text": "#0f172a",
                    "accent": "#facc15",
                },
                "message": "Proclamação da República: marco histórico da nossa nação. Nossas unidades estarão fechadas nesta data.",
                "badge": "Proclamação da República",
                "title": "15 de Novembro",
                "navbar_gif": "images/themes/independencia_brasil.gif",
            },
        ),
        (
            lambda n: "tiradentes" in n,
            {
                "colors": {
                    "hero_start": "#b45309",
                    "hero_end": "#d97706",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(255,248,220,0.92)",
                    "badge_text": "#92400e",
                    "accent": "#d97706",
                },
                "message": "Tiradentes: memória e liberdade. Nossas unidades estarão fechadas nesta data em respeito ao feriado nacional.",
                "badge": "Dia de Tiradentes",
                "title": "Memória e Liberdade",
                "navbar_gif": "images/themes/independencia_brasil.gif",
            },
        ),
        (
            lambda n: "trabalhador" in n or "trabalho" in n,
            {
                "colors": {
                    "hero_start": "#1e3a8a",
                    "hero_end": "#0284c7",
                    "hero_text": "#ffffff",
                    "badge_bg": "rgba(2,132,199,0.15)",
                    "badge_text": "#38bdf8",
                    "accent": "#0284c7",
                },
                "message": "Dia Mundial do Trabalho: reconhecimento a toda a nossa equipe que constrói o sucesso da Sollus diariamente. Nossas unidades estarão fechadas nesta data.",
                "badge": "Dia do Trabalhador",
                "title": "Dia Mundial do Trabalho",
                "navbar_gif": "images/themes/independencia_brasil.gif",
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
                    "accent": "#94a3b8",
                },
                "message": "Dia de Finados: momento de respeito, memória e gratidão. Nossas unidades estarão fechadas nesta data.",
                "badge": "Finados",
                "title": "Memória e Respeito",
                "navbar_gif": "images/themes/finados_vela.gif",
            },
        ),
        (
            lambda n: "carnaval" in n,
            {
                "colors": {
                    "hero_start": "#7c3aed",
                    "hero_end": "#db2777",
                    "hero_text": "#fdf4ff",
                    "badge_bg": "rgba(253,244,255,0.85)",
                    "badge_text": "#6d28d9",
                    "accent": "#ec4899",
                },
                "message": "Carnaval: celebração da cultura brasileira. Nossas unidades estarão fechadas durante os dias de folia.",
                "badge": "Carnaval",
                "title": "Carnaval",
                "navbar_gif": "images/themes/carnaval_mascara.gif",
            },
        ),
        (
            lambda n: "pscoa" in n or "pascoa" in n or "paixao" in n or "sexta-feira santa" in n or "sexta feira santa" in n,
            {
                "colors": {
                    "hero_start": "#6d28d9",
                    "hero_end": "#ec4899",
                    "hero_text": "#fdf4ff",
                    "badge_bg": "rgba(250,240,255,0.9)",
                    "badge_text": "#6d28d9",
                    "accent": "#a855f7",
                },
                "message": "Páscoa: tempo de renovação e harmonia. Nossas unidades estarão fechadas nesta data.",
                "badge": "Páscoa",
                "title": "Renovação e Harmonia",
                "navbar_gif": "images/themes/pascoa_coelhinho.gif",
            },
        ),
        (
            lambda n: "corpus christi" in n,
            {
                "colors": {
                    "hero_start": "#4338ca",
                    "hero_end": "#7c3aed",
                    "hero_text": "#f8fafc",
                    "badge_bg": "rgba(248,250,252,0.9)",
                    "badge_text": "#6d28d9",
                    "accent": "#8b5cf6",
                },
                "message": "Corpus Christi: momento de reflexão e serenidade. As unidades fechadas na localidade retomam o atendimento no próximo dia útil.",
                "badge": "Corpus Christi",
                "title": "Corpus Christi",
                "navbar_gif": "images/themes/feriado_cwb.gif",
            },
        ),
        (
            lambda n: "conscincia negra" in n or "consciencia negra" in n or "zumbi" in n,
            {
                "colors": {
                    "hero_start": "#7f1d1d",
                    "hero_end": "#0f172a",
                    "hero_text": "#fef2f2",
                    "badge_bg": "rgba(127,29,29,0.18)",
                    "badge_text": "#f1f5f9",
                    "accent": "#ef4444",
                },
                "message": "Dia da Consciência Negra: fortalecemos a diversidade, o respeito e a igualdade. Nossas unidades estarão fechadas nesta data.",
                "badge": "Consciência Negra",
                "title": "Diversidade e Respeito",
                "navbar_gif": "images/themes/consciencia_negra.gif",
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


def _calculate_easter(year: int) -> date:
    """Calcula o Domingo de Páscoa pelo algoritmo canônico de Meeus/Jones/Butcher."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _get_sollus_unit_holidays(year: int) -> list[dict[str, Any]]:
    """Gera automaticamente todos os feriados regionais das unidades Sollus (RJ, SP, ES, CWB) para qualquer ano."""
    easter = _calculate_easter(year)
    penha_date = easter + timedelta(days=8)
    corpus_date = easter + timedelta(days=60)

    return [
        {
            "date": f"{year}-01-20",
            "name": "Dia de São Sebastião",
            "badge": "Feriado Municipal • Rio de Janeiro",
            "title": "São Sebastião — Feriado no Rio de Janeiro (RJ)",
            "message": "Hoje é feriado municipal no Rio de Janeiro (RJ). A unidade RJ estará fechada nesta data; as demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Rio de Janeiro",
            "state": "RJ",
            "priority": 350,
            "colors": {"hero_start": "#0369a1", "hero_end": "#0284c7", "hero_text": "#ffffff", "badge_bg": "rgba(2,132,199,0.15)", "badge_text": "#38bdf8", "accent": "#0284c7"},
            "navbar_gif": "images/themes/feriado_rj.gif",
        },
        {
            "date": f"{year}-04-23",
            "name": "Dia de São Jorge",
            "badge": "Feriado Estadual • Rio de Janeiro",
            "title": "Dia de São Jorge — Feriado Estadual no RJ",
            "message": "Hoje é feriado estadual no Rio de Janeiro (RJ). As unidades do estado do RJ (Capital e Campos) estarão fechadas nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "estadual",
            "city": "Rio de Janeiro",
            "state": "RJ",
            "priority": 350,
            "colors": {"hero_start": "#b91c1c", "hero_end": "#dc2626", "hero_text": "#ffffff", "badge_bg": "rgba(220,38,38,0.15)", "badge_text": "#f87171", "accent": "#dc2626"},
            "navbar_gif": "images/themes/feriado_rj.gif",
        },
        {
            "date": f"{year}-01-15",
            "name": "Dia de Santo Amaro",
            "badge": "Feriado Municipal • Campos dos Goytacazes",
            "title": "Dia de Santo Amaro — Feriado em Campos (RJ)",
            "message": "Hoje é feriado municipal em Campos dos Goytacazes (RJ). A unidade Campos estará fechada nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Campos dos Goytacazes",
            "state": "RJ",
            "priority": 350,
            "colors": {"hero_start": "#15803d", "hero_end": "#16a34a", "hero_text": "#ffffff", "badge_bg": "rgba(22,163,74,0.15)", "badge_text": "#4ade80", "accent": "#16a34a"},
            "navbar_gif": "images/themes/feriado_rj.gif",
        },
        {
            "date": f"{year}-08-06",
            "name": "Santíssimo Salvador",
            "badge": "Feriado Municipal • Campos dos Goytacazes",
            "title": "Santíssimo Salvador — Feriado em Campos (RJ)",
            "message": "Hoje é feriado municipal em Campos dos Goytacazes (RJ). A unidade Campos estará fechada nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Campos dos Goytacazes",
            "state": "RJ",
            "priority": 350,
            "colors": {"hero_start": "#b45309", "hero_end": "#d97706", "hero_text": "#ffffff", "badge_bg": "rgba(217,119,6,0.15)", "badge_text": "#fbbf24", "accent": "#d97706"},
            "navbar_gif": "images/themes/feriado_rj.gif",
        },
        {
            "date": f"{year}-01-25",
            "name": "Aniversário de São Paulo",
            "badge": "Feriado Municipal • São Paulo",
            "title": "Aniversário de São Paulo — Feriado em SP",
            "message": "Hoje é feriado municipal em São Paulo (SP) em comemoração ao aniversário da capital paulista. Unidade SP estará fechada nesta data; demais unidades operando normalmente.",
            "level": "municipal",
            "city": "São Paulo",
            "state": "SP",
            "priority": 350,
            "colors": {"hero_start": "#be123c", "hero_end": "#e11d48", "hero_text": "#ffffff", "badge_bg": "rgba(225,29,72,0.15)", "badge_text": "#fb7185", "accent": "#e11d48"},
            "navbar_gif": "images/themes/feriado_sp.gif",
        },
        {
            "date": f"{year}-07-09",
            "name": "Revolução Constitucionalista de 1932",
            "badge": "Feriado Estadual • São Paulo",
            "title": "Revolução Constitucionalista — Feriado Estadual em SP",
            "message": "Hoje é feriado estadual em São Paulo (SP). A unidade SP estará fechada nesta data; as demais unidades seguem operando normalmente.",
            "level": "estadual",
            "city": "São Paulo",
            "state": "SP",
            "priority": 350,
            "colors": {"hero_start": "#1e293b", "hero_end": "#b91c1c", "hero_text": "#ffffff", "badge_bg": "rgba(255,255,255,0.15)", "badge_text": "#f1f5f9", "accent": "#e11d48"},
            "navbar_gif": "images/themes/feriado_sp.gif",
        },
        {
            "date": penha_date.isoformat(),
            "name": "Nossa Senhora da Penha",
            "badge": "Feriado Estadual • Espírito Santo",
            "title": "Nossa Senhora da Penha — Feriado Estadual no ES",
            "message": "Hoje é feriado estadual no Espírito Santo em homenagem à padroeira do estado. A unidade ES estará fechada nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "estadual",
            "city": "Vitória",
            "state": "ES",
            "priority": 380,
            "colors": {"hero_start": "#0284c7", "hero_end": "#0ea5e9", "hero_text": "#ffffff", "badge_bg": "rgba(14,165,233,0.15)", "badge_text": "#38bdf8", "accent": "#0ea5e9"},
            "navbar_gif": "images/themes/feriado_es.gif",
        },
        {
            "date": f"{year}-05-23",
            "name": "Colonização do Solo Espírito-Santense",
            "badge": "Feriado Municipal • Vila Velha (ES)",
            "title": "Colonização do Solo Espírito-Santense — Feriado em Vila Velha (ES)",
            "message": "Hoje é feriado municipal em Vila Velha (ES). A unidade ES estará fechada nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Vila Velha",
            "state": "ES",
            "priority": 350,
            "colors": {"hero_start": "#0d9488", "hero_end": "#14b8a6", "hero_text": "#ffffff", "badge_bg": "rgba(20,184,166,0.15)", "badge_text": "#2dd4bf", "accent": "#14b8a6"},
            "navbar_gif": "images/themes/feriado_es.gif",
        },
        {
            "date": f"{year}-09-08",
            "name": "Aniversário de Vitória e Padroeira de Curitiba",
            "badge": "Feriado Municipal • Vitória e Curitiba",
            "title": "Feriado Municipal em Vitória (ES) e Curitiba (PR)",
            "message": "Hoje é feriado municipal em Vitória (ES) e em Curitiba (PR). As unidades ES e CWB estarão fechadas nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Vitória e Curitiba",
            "state": "ES/PR",
            "priority": 350,
            "colors": {"hero_start": "#4338ca", "hero_end": "#6366f1", "hero_text": "#ffffff", "badge_bg": "rgba(99,102,241,0.15)", "badge_text": "#818cf8", "accent": "#6366f1"},
            "navbar_gif": "images/themes/feriado_cwb.gif",
        },
        {
            "date": corpus_date.isoformat(),
            "name": "Corpus Christi",
            "badge": "Feriado Municipal • Curitiba (PR)",
            "title": "Corpus Christi — Feriado Municipal em Curitiba (PR)",
            "message": "Hoje é feriado municipal em Curitiba (PR). A unidade CWB estará fechada nesta data; demais unidades da Sollus seguem operando normalmente.",
            "level": "municipal",
            "city": "Curitiba",
            "state": "PR",
            "priority": 350,
            "colors": {"hero_start": "#6d28d9", "hero_end": "#8b5cf6", "hero_text": "#ffffff", "badge_bg": "rgba(139,92,246,0.15)", "badge_text": "#a78bfa", "accent": "#8b5cf6"},
            "navbar_gif": "images/themes/feriado_cwb.gif",
        },
    ]


def _collect_holiday_entries(year: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    # 1. Feriados das unidades Sollus (RJ, SP, ES, CWB)
    sollus_unit_entries = _get_sollus_unit_holidays(year)
    entries.extend({**item, "_source": "sollus_units"} for item in sollus_unit_entries)

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

        location_msg = "em todo o país"
        if level.startswith("estadua") and state:
            location_msg = f"no estado de {state.upper()}"
        elif city:
            location_msg = f"em {city.title()}"

        custom_message = item.get("message") or style_info.get("message")
        if custom_message:
            if "{location}" in custom_message:
                message = custom_message.format(location=location_msg)
            else:
                message = custom_message
        else:
            message = (
                f"Hoje celebramos {name} {location_msg}. As unidades locais estarão fechadas nesta data, retornando ao expediente normal no próximo dia útil."
            )

        badge_text = item.get("badge") or style_info.get("badge") or name
        title_text = item.get("title") or style_info.get("title") or name
        colors = item.get("colors") or colors
        navbar_gif = item.get("navbar_gif") or style_info.get("navbar_gif")

        priority = item.get("priority") or LEVEL_PRIORITIES.get(level, 220)
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
        if navbar_gif:
            theme["navbar_gif"] = navbar_gif

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
        if theme.get("holiday_type") in ("municipal", "city", "municipio", "estadual", "state"):
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

