"""Calibrated token estimate, size bounds and script-level measurement for composed labels."""

from __future__ import annotations

from collections.abc import Callable

from glyphforge.canon import tokenize
from glyphforge.errors.api import Site, token_spans

# Linear fit tokens ~= a * len(tokenize(label)) + b, calibrated on 3,000 labels against the LightOnOCR-3-4B tokenizer (r=0.983).
TOKEN_FIT = (0.92, 6.5)
_LEVELS = ("base", "script", "scriptscript")


def est_tokens(label: str) -> int:
    return round(TOKEN_FIT[0] * len(tokenize(label)) + TOKEN_FIT[1])


def nesting_depth(latex: str) -> int:
    depth = best = 0
    for tok, _, _ in token_spans(latex):
        depth += (tok == "{") - (tok == "}")
        best = max(best, depth)
    return best


def script_count(latex: str) -> int:
    return sum(tok in ("^", "_") for tok, _, _ in token_spans(latex))


def site_level(latex: str, site: Site) -> str:
    """base / script / scriptscript for the site, from the script brace groups open before it."""
    stack: list[bool] = []
    prev = ""
    for tok, start, _ in token_spans(latex):
        if start >= site.start:
            break
        if tok == "{":
            stack.append(prev in ("^", "_"))
        elif tok == "}" and stack:
            stack.pop()
        prev = tok
    return _LEVELS[min(sum(stack) + (prev in ("^", "_")), 2)]


def bounds_problem(label: str, *, max_tokens: int, max_depth: int, max_scripts: int, counter: Callable[[str], int] | None = None) -> str | None:
    if (counter or est_tokens)(label) > max_tokens:
        return "over-token-cap"
    if nesting_depth(label) > max_depth:
        return "too-deep"
    if script_count(label) > max_scripts:
        return "too-many-scripts"
    return None
