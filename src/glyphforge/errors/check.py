"""Contract checks every error class (built-in or user) must pass."""

from __future__ import annotations

from collections.abc import Iterable

from glyphforge.canon import canonicalize, equivalent, tokenize
from glyphforge.canon.label import structural_problems
from glyphforge.canon.safety import check_render
from glyphforge.errors.api import NAME_RE, PACKAGE_RE, ErrorClass
from glyphforge.rng import slot_rng


def check_error_class(cls: ErrorClass, formulas: Iterable[str]) -> list[str]:
    """Problems with ``cls`` over ``formulas``; [] means the class honours the contract."""
    if not isinstance(cls, ErrorClass):
        return [f"{cls!r}: does not implement ErrorClass"]
    problems = [
        f"{cls.name}: {msg}"
        for ok, msg in (
            (isinstance(cls.name, str) and NAME_RE.match(cls.name), "bad name"),
            (isinstance(cls.version, str) and cls.version, "bad version"),
            (isinstance(cls.family, str) and cls.family, "bad family"),
            (isinstance(cls.packages, frozenset) and all(PACKAGE_RE.match(p) for p in cls.packages), "bad packages"),
        )
        if not ok
    ]
    seen = False
    for latex in formulas:
        pre = f"{cls.name}: {latex!r}: "
        sites = cls.sites(latex)
        if sites != cls.sites(latex):
            problems.append(pre + "non-deterministic sites")
            continue
        seen = seen or bool(sites)
        variants = [cls.apply(latex, s, slot_rng(0, "check", i)) for i, s in enumerate(sites)]
        reverse = [cls.apply(latex, s, slot_rng(0, "check", i)) for i, s in reversed(list(enumerate(sites)))]
        if variants != reverse[::-1]:
            problems.append(pre + "non-deterministic apply")
        problems += [pre + f"site {s} out of range" for s in sites if not 0 <= s.start < s.end <= len(latex)]
        for v in variants:
            if not v.control_glyph:
                problems.append(pre + "empty control_glyph")
            if v.target == v.hard_negative or equivalent(v.target, v.hard_negative):
                problems.append(pre + f"target and hard negative are normalize-equal: {v.target!r}")
            for label, extra in ((v.target, v.target_alternates), (v.hard_negative, v.hard_negative_alternates)):
                problems += [pre + f"{label!r}: {p}" for p in (check_render(label), *structural_problems(label)) if p]
                if tokenize(canonicalize(label, "equation")) != tokenize(label):
                    problems.append(pre + f"{label!r}: label rewritten by canon")
                for alt in extra:
                    problems += [pre + f"alternate {alt!r}: {p}" for p in [check_render(alt)] if p]
                    if equivalent(alt, label):
                        problems.append(pre + f"alternate {alt!r} normalize-equal to its label")
    if not seen:
        problems.append(f"{cls.name}: no sites in any formula")
    return problems
