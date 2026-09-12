from __future__ import annotations

from .base import DeliveryResult, Downloader, Method
from .thunder import Thunder

_BUILTIN: tuple[type[Downloader], ...] = (
    Thunder,
)

_cache: dict[str, bool] = {}

def all_downloaders() -> list[Downloader]:
    return [cls() for cls in _BUILTIN]

def available_downloaders(refresh: bool = False) -> list[Downloader]:
    if refresh:
        _cache.clear()
    out: list[Downloader] = []
    for cls in _BUILTIN:
        key = cls.key
        if key not in _cache:
            _cache[key] = _safe_available(cls())
        if _cache[key]:
            out.append(cls())
    return out

def pick_default(preferred: str | None = None,
                 refresh: bool = False) -> Downloader | None:
    if refresh:
        _cache.clear()

    if preferred:
        cls = next((c for c in _BUILTIN if c.key == preferred), None)
        if cls is not None:
            key = cls.key
            if key not in _cache:
                _cache[key] = _safe_available(cls())
            if _cache[key]:
                return cls()

    usable = available_downloaders()
    return usable[0] if usable else None

def _safe_available(inst: Downloader) -> bool:
    try:
        return bool(inst.available())
    except Exception:
        return False

def _safe(method: Method) -> bool:
    try:
        return bool(method.available())
    except Exception:
        return False

__all__ = [
    "DeliveryResult",
    "Downloader",
    "Method",
    "Thunder",
    "all_downloaders",
    "available_downloaders",
    "pick_default",
]

