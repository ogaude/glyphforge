"""Drop-reason vocabulary and the (class x style) survival report; zero-yield cells are reported, never backfilled."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from glyphforge.render import STATUSES

REASONS = tuple(s for s in STATUSES if s != "rendered") + ("ambiguous-identical", "pair_partner_dropped")


def _cell() -> dict:
    return {"planned": 0, "kept": 0, "dropped": Counter(), "flags": Counter()}


def survival(entries: Iterable[tuple[str, str, str | None, tuple[str, ...]]], cells: Iterable[tuple[str, str]]) -> dict:
    table = {c: _cell() for c in cells}
    for cls, style, reason, flags in entries:
        if reason is not None and reason not in REASONS:
            raise ValueError(f"unknown drop reason {reason!r}; expected one of {REASONS}")
        cell = table.setdefault((cls, style), _cell())
        cell["planned"] += 1
        if reason is None:
            cell["kept"] += 1
        else:
            cell["dropped"][reason] += 1
        cell["flags"].update(flags)
    return {
        "cells": {
            f"{c}|{s}": {"planned": v["planned"], "kept": v["kept"], "dropped": dict(sorted(v["dropped"].items())), "flags": dict(sorted(v["flags"].items()))}
            for (c, s), v in sorted(table.items())
        },
        "zero_yield": [[c, s] for (c, s), v in sorted(table.items()) if v["kept"] == 0],
    }
