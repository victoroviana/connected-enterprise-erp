"""Legacy compatibility layer for blueprints.auth imports."""
from importlib import import_module

from .. import _alias_submodule, _export_module

_impl = import_module("modules.propostas.blueprints.auth")
__all__ = _export_module(_impl, globals())

for _submod in ("login", "usuarios", "permissoes", "permissions_utils"):
    try:
        _alias_submodule(f"{__name__}.{_submod}", f"modules.propostas.blueprints.auth.{_submod}")
    except ModuleNotFoundError:
        continue

del _impl
