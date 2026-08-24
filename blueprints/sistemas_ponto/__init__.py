"""Legacy compatibility layer for blueprints.sistemas_ponto imports."""
from importlib import import_module

from .. import _alias_submodule, _export_module

_impl = import_module("modules.propostas.blueprints.sistemas_ponto")
__all__ = _export_module(_impl, globals())

for _submod in ("sistemas",):
    try:
        _alias_submodule(f"{__name__}.{_submod}", f"modules.propostas.blueprints.sistemas_ponto.{_submod}")
    except ModuleNotFoundError:
        continue


del _impl
