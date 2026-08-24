"""Legacy compatibility layer for blueprints.equipamentos imports."""
from importlib import import_module

from .. import _alias_submodule, _export_module

_impl = import_module("modules.propostas.blueprints.equipamentos")
__all__ = _export_module(_impl, globals())

for _submod in ("routes",):
    try:
        _alias_submodule(f"{__name__}.{_submod}", f"modules.propostas.blueprints.equipamentos.{_submod}")
    except ModuleNotFoundError:
        continue


del _impl
