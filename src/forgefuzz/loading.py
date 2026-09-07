from __future__ import annotations

import importlib
from importlib import metadata
from typing import Any

from .adapters import NumPyAdapter, PyTorchAdapter, PythonAdapter
from .plugin import LanguageAdapter

BUILTIN_ADAPTERS: dict[str, type[LanguageAdapter]] = {
    "python": PythonAdapter,
    "pytorch": PyTorchAdapter,
    "numpy": NumPyAdapter,
}
ENTRY_POINT_GROUP = "forgefuzz.adapters"


def _instantiate(value: Any) -> LanguageAdapter:
    instance = value() if isinstance(value, type) else value
    if not isinstance(instance, LanguageAdapter):
        raise TypeError(f"adapter must implement LanguageAdapter, got {type(instance).__name__}")
    return instance


def load_adapter(spec: str) -> LanguageAdapter:
    """Load a builtin, installed entry point, or ``module:object`` adapter."""
    if spec in BUILTIN_ADAPTERS:
        return BUILTIN_ADAPTERS[spec]()
    for entry_point in metadata.entry_points().select(group=ENTRY_POINT_GROUP, name=spec):
        return _instantiate(entry_point.load())
    if ":" not in spec:
        raise ValueError(
            f"unknown adapter {spec!r}; use a builtin name, installed entry point, "
            "or module.path:AdapterClass"
        )
    module_name, object_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    return _instantiate(getattr(module, object_name))


def available_adapters() -> list[tuple[str, str]]:
    values = [(name, "builtin") for name in BUILTIN_ADAPTERS]
    values.extend(
        (entry.name, entry.value)
        for entry in metadata.entry_points().select(group=ENTRY_POINT_GROUP)
    )
    return sorted(values)
