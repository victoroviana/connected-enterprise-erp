"""Compatibility package for legacy blueprint import paths.

This module keeps the old import blueprints.* statements working by
forwarding them to the new package structure under
modules.propostas.blueprints. The actual implementations continue to
live in their modern modules; we merely expose lightweight aliases.
"""
from importlib import import_module
import sys
from types import ModuleType
from typing import Tuple


def _alias_submodule(shim_name: str, target: str) -> ModuleType:
    """Register shim_name in sys.modules pointing at target."""
    module = import_module(target)
    sys.modules[shim_name] = module

    parent_name, _, attr = shim_name.rpartition(".")
    if parent_name:
        parent_module = sys.modules.get(parent_name)
        if parent_module is None:
            parent_module = ModuleType(parent_name)
            sys.modules[parent_name] = parent_module
        setattr(parent_module, attr, module)
    return module


def _public_names(module: ModuleType) -> Tuple[str, ...]:
    exported = getattr(module, "__all__", None)
    if exported is not None:
        return tuple(exported)
    return tuple(name for name in dir(module) if not name.startswith("_"))


def _export_module(module: ModuleType, namespace: dict) -> Tuple[str, ...]:
    names = _public_names(module)
    for name in names:
        namespace[name] = getattr(module, name)
    return names


__all__: Tuple[str, ...] = ()
