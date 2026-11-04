"""Mine ConfusionPairs from (truth, predicted, count) alignment rows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from glyphforge.canon import equivalent
from glyphforge.errors.api import ConfusionPair, token_spans


def _slug(token: str) -> str:
    return "".join(c if c.isascii() and c.isalnum() else f"u{ord(c):x}" for c in token.removeprefix("\\"))


def pairs_from_alignment(
    rows: Iterable[tuple[str, str, int]], *, family: str = "mined", prefix: str = "mined", min_count: int = 1
) -> list[ConfusionPair]:
    totals: Counter[tuple[str, str]] = Counter()
    for truth, pred, n in rows:
        if len(token_spans(truth)) == 1 and len(token_spans(pred)) == 1 and truth != pred and not equivalent(truth, pred):
            totals[truth, pred] += n
    ranked = sorted(((t, p, n) for (t, p), n in totals.items() if n >= min_count), key=lambda r: (-r[2], r[0], r[1]))
    return [ConfusionPair(f"{prefix}.{_slug(t)}_{_slug(p)}", t, p, family) for t, p, _ in ranked]
