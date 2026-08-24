"""Legacy compatibility shim for blueprints.decorators imports."""
from importlib import import_module

_impl = import_module("modules.propostas.blueprints.decorators")
__all__ = getattr(_impl, "__all__", tuple(name for name in dir(_impl) if not name.startswith("_")))

globals().update({name: getattr(_impl, name) for name in __all__})


del _impl
