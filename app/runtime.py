from __future__ import annotations

from typing import Any

_values: dict = {}


def replace(values: dict) -> None:
    _values.clear()
    _values.update(values or {})


def get(key: str, default=None) -> Any:
    return _values.get(key, default)


