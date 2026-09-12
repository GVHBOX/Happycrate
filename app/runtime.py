from __future__ import annotations

_values: dict = {}


def replace(values: dict) -> None:
    _values.clear()
    _values.update(values or {})


def get(key: str, default=None):
    return _values.get(key, default)


