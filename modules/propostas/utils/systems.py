"""System catalog and helpers for proposal forms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional
from types import SimpleNamespace

from flask import has_app_context


@dataclass(frozen=True)
class SystemOption:
    """Represents a selectable system template."""

    key: str
    label: str
    description: str
    image: str
    default_quantity: int
    unit_price: float

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "image": self.image,
            "default_quantity": self.default_quantity,
            "unit_price": self.unit_price,
        }


DEFAULT_SYSTEM_OPTIONS: Dict[str, SystemOption] = {
    "rhid": SystemOption(
        key="rhid",
        label="RHiD",
        description="Plataforma RHiD para gestão completa de Recursos Humanos.",
        image="static/images/rhid.png",
        default_quantity=1,
        unit_price=0.0,
    ),
    "sollus_access": SystemOption(
        key="sollus_access",
        label="Sollus Access",
        description="Sollus Access - controle de acesso integrado e inteligente.",
        image="static/images/sollus.png",
        default_quantity=1,
        unit_price=0.0,
    ),
    "velti_ponto": SystemOption(
        key="velti_ponto",
        label="Velti Ponto",
        description="Velti Ponto para monitoramento eletrônico da jornada.",
        image="static/images/velti.png",
        default_quantity=1,
        unit_price=0.0,
    ),
    "henry_ponto": SystemOption(
        key="henry_ponto",
        label="Henry Ponto",
        description="Henry Ponto homologado para controle de ponto.",
        image="static/images/henry.png",
        default_quantity=1,
        unit_price=0.0,
    ),
    "secullum": SystemOption(
        key="secullum",
        label="Secullum",
        description="Secullum - plataforma para gestão de ponto e acesso.",
        image="static/images/secullum.png",
        default_quantity=1,
        unit_price=0.0,
    ),
}


def _clone_option(option: SystemOption) -> SystemOption:
    return SystemOption(
        key=option.key,
        label=option.label,
        description=option.description,
        image=option.image,
        default_quantity=option.default_quantity,
        unit_price=option.unit_price,
    )


def _load_override_map() -> Dict[str, "SystemOptionOverride"]:
    if not has_app_context():
        return {}
    try:
        from modules.propostas.models import SystemOptionOverride
    except Exception:
        return {}
    try:
        overrides = SystemOptionOverride.query.all()
    except Exception:
        return {}
    return {ov.key: ov for ov in overrides}


def _load_system_states() -> Dict[str, "SystemOptionState"]:
    if not has_app_context():
        return {}
    try:
        from modules.propostas.models import SystemOptionState
    except Exception:
        return {}
    try:
        states = SystemOptionState.query.all()
    except Exception:
        return {}
    return {state.key: state for state in states}


def _load_custom_options() -> list["SystemOptionCatalog"]:
    if not has_app_context():
        return []
    try:
        from modules.propostas.models import SystemOptionCatalog
    except Exception:
        return []
    try:
        return SystemOptionCatalog.query.all()
    except Exception:
        return []


def _system_options_map() -> Dict[str, SystemOption]:
    states = _load_system_states()
    disabled = {key for key, state in states.items() if not state.is_active}
    options = {
        key: _clone_option(opt)
        for key, opt in DEFAULT_SYSTEM_OPTIONS.items()
        if key not in disabled
    }
    overrides = _load_override_map()
    for key, override in overrides.items():
        base = options.get(key)
        if not base:
            # Skip unknown keys until defaults are configured
            continue
        options[key] = SystemOption(
            key=base.key,
            label=base.label,
            description=override.description or base.description,
            image=override.image_path or base.image,
            default_quantity=base.default_quantity,
            unit_price=base.unit_price,
        )
    for custom in _load_custom_options():
        if not custom or not custom.key or custom.key in options or custom.key in disabled:
            continue
        options[custom.key] = SystemOption(
            key=custom.key,
            label=custom.label,
            description=custom.description or "",
            image=custom.image_path or "",
            default_quantity=custom.default_quantity or 1,
            unit_price=custom.unit_price or 0.0,
        )
    return options


def iter_system_options() -> Iterable[SystemOption]:
    return _system_options_map().values()


def get_system_option(key: Optional[str]) -> Optional[SystemOption]:
    if not key:
        return None
    return _system_options_map().get(key)


def build_system_item(
    option: SystemOption,
    quantity: Optional[int] = None,
    unit_price: Optional[float] = None,
    total_price: Optional[float] = None,
    is_fixo: bool = False,
    description: Optional[str] = None,
):
    qty = option.default_quantity if quantity is None else max(1, quantity)
    price = option.unit_price if unit_price is None else max(0.0, unit_price)
    override = None if total_price is None else max(0.0, float(total_price))

    return SimpleNamespace(
        id=f"system:{option.key}",
        name=option.label,
        description=description if description is not None else option.description,
        illustration_path=option.image,
        quantity=qty,
        unit_price=price,
        discount_percent=0.0,
        total_override=override,
        is_fixo=is_fixo,
        is_acquisition=False,
        is_system=True,
    )


def serialize_system_payload(option: SystemOption, quantity: int, unit_price: float, is_fixo: bool = False) -> dict:
    return {
        "key": option.key,
        "quantity": int(quantity),
        "unit_price": float(unit_price),
        "is_fixo": is_fixo,
    }


import re

def parse_unit_price(value: any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    
    raw = str(value).strip()
    if not raw:
        return 0.0
        
    # Remove everything except digits, dots and commas
    cleaned = re.sub(r'[^\d,.]', '', raw)
    if not cleaned:
        return 0.0
        
    # In Brazil, we use comma for decimals and dot for thousands.
    # However, someone might type 129.90.
    # Logic: if there are both dot and comma, the dot is thousands, comma is decimal.
    # If there is only one type of separator, we check if it's near the end.
    
    if ',' in cleaned and '.' in cleaned:
        # 1.234,56 -> 1234.56
        val = cleaned.replace('.', '').replace(',', '.')
    elif ',' in cleaned:
        # 1234,56 -> 1234.56
        val = cleaned.replace(',', '.')
    elif '.' in cleaned:
        # Could be 1.234 (thousands) or 123.45 (decimal)
        # If there are exactly 3 digits after the dot, and it's not the only dot, 
        # or if there's more than one dot, it's thousands.
        parts = cleaned.split('.')
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            # Likely thousands: 1.234 or 1.234.567
            val = cleaned.replace('.', '')
        else:
            # Likely decimal: 123.45
            val = cleaned
    else:
        val = cleaned
        
    try:
        return float(val)
    except ValueError:
        return 0.0



