"""Error-class registry: library register(), recipe plugin modules, entry points."""

from __future__ import annotations

import difflib
import importlib
import importlib.metadata
import re

from glyphforge.errors.api import NAME_RE, ErrorClass

ENTRY_POINT_GROUP = "glyphforge.error_classes"
# Same pattern as recipe.schema.MODULE_RE, duplicated as a literal so errors/ never imports pydantic.
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
BUILTIN_MODULES = (
    "glyphforge.errors.builtin.primes",
    "glyphforge.errors.builtin.greek",
    "glyphforge.errors.builtin.digits",
    "glyphforge.errors.builtin.decorations",
    "glyphforge.errors.builtin.alphabets",
)


class Registry:
    def __init__(self) -> None:
        self._classes: dict[str, ErrorClass] = {}
        self.modules: list[str] = []
        self.entry_points: list[str] = []

    def register(self, obj: ErrorClass) -> ErrorClass:
        if not isinstance(obj, ErrorClass):
            raise TypeError(f"{obj!r} does not implement ErrorClass")
        if not NAME_RE.match(obj.name):
            raise ValueError(f"bad error-class name {obj.name!r}")
        if obj.name in self._classes:
            raise ValueError(f"error class {obj.name!r} is already registered")
        self._classes[obj.name] = obj
        return obj

    def get(self, name: str) -> ErrorClass:
        if name not in self._classes:
            close = difflib.get_close_matches(name, self._classes, n=3)
            raise KeyError(f"unknown error class {name!r}" + (f"; did you mean {', '.join(close)}?" if close else ""))
        return self._classes[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._classes))

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(f"{c.name}@{c.version}" for c in self._classes.values()))

    def load_module(self, module: str) -> None:
        """Import ``module`` by dotted name and call its ``register_classes(registry)``."""
        if not MODULE_RE.match(module):
            raise ValueError(f"bad plugin module name {module!r}")
        hook = getattr(importlib.import_module(module), "register_classes", None)
        if not callable(hook):
            raise ValueError(f"plugin module {module!r} has no register_classes(registry)")  # noqa: TRY004
        hook(self)
        self.modules.append(module)

    def load_entry_points(self) -> None:
        for ep in sorted(importlib.metadata.entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
            obj = ep.load()
            self.register(obj) if isinstance(obj, ErrorClass) else obj(self)
            self.entry_points.append(f"{ep.name}={ep.dist.name}@{ep.dist.version}" if ep.dist else ep.name)

    def extend(self, other: Registry) -> None:
        for cls in other._classes.values():
            self.register(cls)


DEFAULT_REGISTRY = Registry()
register = DEFAULT_REGISTRY.register


def builtin_registry() -> Registry:
    reg = Registry()
    for module in BUILTIN_MODULES:
        reg.load_module(module)
    return reg
