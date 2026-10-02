"""
utils/cache.py - Cache em memória leve e thread-safe com TTL para o Sollus Connected.
Usado para acelerar consultas frequentes a tabelas estáticas/configurações (Departamentos, Filiais, etc).
"""
import time
import functools
import threading
from typing import Any, Callable, Dict, Tuple

_cache_store: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def cached(ttl_seconds: int = 300, key_prefix: str | None = None) -> Callable:
    """
    Decorator para armazenar em memória o resultado de uma função por `ttl_seconds`.
    Exemplo:
        @cached(ttl_seconds=600, key_prefix="departments")
        def get_all_departments():
            return Department.query.order_by(Department.name).all()
    """
    def decorator(fn: Callable) -> Callable:
        prefix = key_prefix or f"{fn.__module__}.{fn.__name__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Gera a chave de cache baseada nos argumentos
            key_parts = [prefix]
            if args:
                key_parts.extend(str(a) for a in args)
            if kwargs:
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            now = time.time()
            with _cache_lock:
                if cache_key in _cache_store:
                    expires_at, value = _cache_store[cache_key]
                    if now < expires_at:
                        return value
                    else:
                        del _cache_store[cache_key]

            # Executa a função e armazena o resultado
            result = fn(*args, **kwargs)

            with _cache_lock:
                _cache_store[cache_key] = (now + ttl_seconds, result)

            return result

        wrapper.clear_cache = lambda: invalidate_cache(prefix)
        return wrapper

    return decorator


def invalidate_cache(prefix: str | None = None) -> int:
    """
    Invalida chaves do cache. Se `prefix` for informado, invalida apenas as que começam com ele.
    Retorna o total de chaves removidas.
    """
    with _cache_lock:
        if prefix is None:
            count = len(_cache_store)
            _cache_store.clear()
            return count

        keys_to_del = [k for k in _cache_store if k.startswith(prefix)]
        for k in keys_to_del:
            del _cache_store[k]
        return len(keys_to_del)
