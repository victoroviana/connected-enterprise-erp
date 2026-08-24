"""Legacy compatibility layer for blueprints.propostas imports."""
from importlib import import_module

from .. import _alias_submodule, _export_module

_impl = import_module("modules.propostas.blueprints.propostas")
__all__ = _export_module(_impl, globals())

for _submod in ("propostas", "bkp_propostas"):
    try:
        _alias_submodule(f"{__name__}.{_submod}", f"modules.propostas.blueprints.propostas.{_submod}")
    except ModuleNotFoundError:
        continue


del _impl
