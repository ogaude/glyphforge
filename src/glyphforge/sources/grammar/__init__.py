"""Licence-free weighted grammar (CC0): budgeted, site-aware formula generation (D-08, D-09)."""

from __future__ import annotations

import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, model_validator

from glyphforge.errors.api import CommandPair, ConfusionPair, ErrorClass, splice, token_spans
from glyphforge.errors.builtin.primes import Prime
from glyphforge.plan.bounds import nesting_depth, script_count, site_level
from glyphforge.rng import pick
from glyphforge.sources.base import Formula

TABLE_VERSION = "1"
DOMAINS = ("math", "astro-ph", "physics")
# Per-formula budgets, below the recipe bounds defaults (440 tokens / depth 6 / 12 scripts) so the planner rarely rejects:
# the script-level wrapper adds up to 2 brace levels and 2 scripts on top of DEPTH and SCRIPTS.
TOKENS, DEPTH, SCRIPTS = 90, 4, 8
PRODUCTIONS = (30, 60)
_REF = r"\$(S|[a-z]+(?:_[a-z]+)*)"
_STARTS = ("start", "start_multiline")
_ARGS = ("A", "R", "x", "ab", "N")
_LEVELS = {"base": 0, "script": 1, "scriptscript": 2}
_TRIES, _FALLBACK_TRIES = 8, 20


class _Production(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rhs: StrictStr
    weight: float = Field(gt=0)


def _terminal(rhs: str) -> bool:
    return "$" not in rhs and not re.search(r"[\^_]", rhs)


class Table(BaseModel):
    """One domain's production table: ``$name`` references a rule, ``$S`` marks the error-class site."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    licence: Literal["CC0-1.0"]
    domain: StrictStr
    version: StrictStr
    rules: dict[str, tuple[_Production, ...]]

    @model_validator(mode="after")
    def _check(self) -> Table:
        for need in (*_STARTS, "var"):
            if need not in self.rules:
                raise ValueError(f"rule {need!r} is missing")
        for name, prods in self.rules.items():
            if not re.fullmatch(r"[a-z_]+", name) or not prods:
                raise ValueError(f"rule {name!r}: bad name or no productions")
            if name not in _STARTS and not any(_terminal(p.rhs) for p in prods):
                raise ValueError(f"rule {name!r}: needs a terminal production (no $ reference, no ^ or _)")
            for p in prods:
                refs = re.findall(_REF, p.rhs)
                if refs.count("S") != (name in _STARTS):
                    raise ValueError(f"rule {name!r}: $S must appear exactly once in start rules and nowhere else ({p.rhs!r})")
                if missing := sorted(set(refs) - {"S"} - set(self.rules)):
                    raise ValueError(f"rule {name!r}: unknown nonterminal {missing}")
                if name == "var" and re.search(r"[\^_]", p.rhs):
                    raise ValueError("rule 'var': productions must be script-free")
        return self


@cache
def load_tables() -> dict[str, Table]:
    tables = {}
    for domain in DOMAINS:
        path = Path(__file__).parent / "tables" / (domain.replace("-", "_") + ".yaml")
        tables[domain] = table = Table.model_validate(yaml.safe_load(path.read_text("utf-8")))
        if not PRODUCTIONS[0] <= (n := sum(map(len, table.rules.values()))) <= PRODUCTIONS[1]:
            raise ValueError(f"table {domain!r} has {n} productions; expected {PRODUCTIONS[0]}..{PRODUCTIONS[1]}")
    return tables


@cache
def _cost(rhs: str) -> tuple[int, int, int]:
    return max(1, len(token_spans(rhs))), nesting_depth(rhs), script_count(rhs)


def _expand(table: Table, name: str, rng: random.Random, left: list[int], depth: int) -> str:
    """Expand a rule within the shared [tokens, scripts] budget and the remaining brace depth; terminals once nothing fits."""
    prods = table.rules[name]
    costs = {p.rhs: _cost(p.rhs) for p in prods}
    pool = [p for p in prods if costs[p.rhs][0] <= left[0] and costs[p.rhs][1] <= depth and costs[p.rhs][2] <= left[1]]
    prod = pick(rng, pool := pool or [p for p in prods if _terminal(p.rhs)], [p.weight for p in pool])
    tokens, nest, scripts = costs[prod.rhs]
    left[0], left[1] = left[0] - tokens, left[1] - scripts
    text, pos = prod.rhs, 0
    while m := re.search(_REF, text[pos:]):
        start, end = pos + m.start(), pos + m.end()
        if m[1] == "S":
            pos = end
            continue
        new = splice(text, start, end, _expand(table, m[1], rng, left, depth - nest))
        text, pos = new, len(new) - (len(text) - end)
    return text


def _var(table: Table, rng: random.Random) -> str:
    return _expand(table, "var", rng, [TOKENS, SCRIPTS], DEPTH)


def _site_text(cls: ErrorClass, table: Table, rng: random.Random) -> str | None:
    """Text that carries a site of ``cls`` (built-in class types only)."""
    if isinstance(cls, ConfusionPair):
        return cls.truth
    if isinstance(cls, CommandPair):
        args = [a for a in _ARGS if re.fullmatch(cls.arg, a)]
        return f"{cls.truth}{{{pick(rng, args, [1] * len(args))}}}" if args else None
    if isinstance(cls, Prime):
        return _var(table, rng) + "'" * (2 if cls.mode == "dquote" else 1)
    return None


@dataclass(frozen=True)
class GrammarSource:
    """Draws CC0 formulas from the domain tables; ``domains`` maps domain name to weight (default: uniform)."""

    domains: Mapping[str, float] | None = None
    tables: Mapping[str, Table] | None = None

    def draw(self, cls: ErrorClass, rng: random.Random, *, level: str = "base", multiline: bool = False) -> Formula | None:
        """A formula whose first site of ``cls`` sits at ``level``, or None when no attempt produced one."""
        tables, weights = self.tables or load_tables(), self.domains or dict.fromkeys(DOMAINS, 1.0)
        names = sorted(weights)
        known = isinstance(cls, ConfusionPair | CommandPair | Prime)
        for _ in range(_TRIES if known else _FALLBACK_TRIES):
            table = tables[pick(rng, names, [weights[n] for n in names])]
            site = _site_text(cls, table, rng) or _var(table, rng)
            for _ in range(_LEVELS[level]):
                site = f"{_var(table, rng)}{pick(rng, '_^', (3, 1))}{{{site}}}"
            latex = _expand(table, _STARTS[multiline], rng, [TOKENS, SCRIPTS], DEPTH)
            m = re.search(_REF, latex)
            latex = splice(latex, m.start(), m.end(), site)  # type: ignore[union-attr]
            if (sites := cls.sites(latex)) and site_level(latex, sites[0]) == level:
                try:
                    return Formula(latex=latex, licence="CC0-1.0", env="align*" if multiline else "equation*")
                except ValidationError:
                    continue
        return None
