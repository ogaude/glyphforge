import random
import re

import pytest
import yaml
from pydantic import ValidationError

from glyphforge.canon.safety import check_safe
from glyphforge.errors import ConfusionPair, Site, Variant, builtin_registry
from glyphforge.plan.bounds import nesting_depth, script_count, site_level
from glyphforge.rng import slot_rng
from glyphforge.sources.grammar import DOMAINS, GrammarSource, Table, load_tables

REG = builtin_registry()
CLASSES = ("greek.upsilon_v", "primes.prime_l", "digits.I_l", "decorations.drop_mathbf", "alphabets.drop_mathbb", "greek.nu_v")
LEVELS = ("base", "script", "scriptscript")


def _table(rules: dict, **kw) -> Table:
    return Table.model_validate({"licence": "CC0-1.0", "domain": "t", "version": "1", "rules": rules, **kw})


def _rule(*items: tuple[str, float]) -> list[dict]:
    return [{"rhs": r, "weight": w} for r, w in items]


def _tiny() -> Table:
    return _table(
        {
            "start": _rule(("$S = $expr", 1)),
            "start_multiline": _rule(("$S &= $expr \\\\ &= $expr", 1)),
            "var": _rule(("x", 1), ("y", 1)),
            "expr": _rule(("$var + $var", 1), ("\\frac{$var}{2}", 1), ("1", 1)),
        }
    )


TINY = GrammarSource({"t": 1}, {"t": _tiny()})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r.pop("start"), "start"),
        (lambda r: r.pop("var"), "var"),
        (lambda r: r.__setitem__("start", _rule(("$expr", 1))), "start"),
        (lambda r: r.__setitem__("start", _rule(("$S $S", 1))), "start"),
        (lambda r: r.__setitem__("expr", _rule(("$S", 1), ("1", 1))), "expr"),
        (lambda r: r.__setitem__("expr", _rule(("$nope", 1), ("1", 1))), "expr"),
        (lambda r: r.__setitem__("expr", _rule(("$var^{2}", 1))), "expr"),
        (lambda r: r.__setitem__("var", _rule(("x_1", 1))), "var"),
        (lambda r: r.__setitem__("Bad", _rule(("1", 1))), "Bad"),
    ],
)
def test_table_syntax_violations_name_the_rule(mutate, message):
    rules = {k: list(v) for k, v in _tiny().model_dump()["rules"].items()}
    mutate(rules)
    with pytest.raises(ValueError, match=message):
        _table(rules)


def test_table_rejects_bad_licence_and_weight():
    base = {k: v for k, v in _tiny().model_dump().items() if k != "licence"}
    with pytest.raises(ValidationError):
        Table.model_validate({**base, "licence": "CC-BY-4.0"})
    with pytest.raises(ValidationError):
        _table({**_tiny().model_dump()["rules"], "var": _rule(("x", 0))})


def test_draw_has_site_and_is_deterministic():
    cls = REG.get("greek.upsilon_v")
    a = TINY.draw(cls, slot_rng(1, "gen", 0), level="base")
    assert a is not None and cls.sites(a.latex)
    assert a == TINY.draw(cls, slot_rng(1, "gen", 0), level="base")
    for i in range(200):
        f = TINY.draw(cls, slot_rng(2, "gen", i))
        assert f is not None and cls.sites(f.latex)


@pytest.mark.parametrize("name", ["primes.prime_l", "digits.I_l", "alphabets.drop_mathbb"])
@pytest.mark.parametrize("level", LEVELS)
def test_site_level(name, level):
    cls = REG.get(name)
    for i in range(100):
        f = TINY.draw(cls, slot_rng(3, name + level, i), level=level)
        assert f is not None and site_level(f.latex, cls.sites(f.latex)[0]) == level


def test_site_text_per_class_type():
    rng = slot_rng(4, "gen", 0)
    assert "\\mathbb{" in TINY.draw(REG.get("alphabets.drop_mathbb"), rng).latex
    assert re.search(r"\\mathbb\{[A-Z]+\}", TINY.draw(REG.get("alphabets.drop_mathbb"), rng).latex)
    assert re.search(r"[xy]'(?!')", TINY.draw(REG.get("primes.dropped"), rng).latex)
    assert re.search(r"[xy]''", TINY.draw(REG.get("primes.dquote"), rng).latex)
    assert "\\ell" in TINY.draw(REG.get("digits.ell_l"), rng).latex


class _Plugin:
    name, version, family, packages = "plug.x", "1", "plug", frozenset()

    def sites(self, latex):
        return tuple(Site(m.start(), m.end(), "x") for m in re.finditer("x", latex))

    def apply(self, latex, site, rng):
        return Variant(latex, latex, "x")


def test_plugin_class_falls_back_to_generate_then_check():
    f = TINY.draw(_Plugin(), slot_rng(5, "gen", 0))
    assert f is not None and "x" in f.latex
    never = ConfusionPair("plug.never", "\\zeta", "z", "plug")
    assert GrammarSource({"t": 1}, {"t": _tiny()}).draw(never, slot_rng(5, "gen", 1)) is not None


def test_control_words_never_merge():
    words = set(re.findall(r"\\[A-Za-z]+", "".join(p.rhs for t in load_tables().values() for ps in t.rules.values() for p in ps)))
    words |= {"\\upsilon", "\\nu", "\\mathbf", "\\mathbb", "\\ell"}
    for i in range(300):
        f = GrammarSource().draw(REG.get(CLASSES[i % 6]), slot_rng(6, "gen", i), level=LEVELS[i % 3])
        assert f is not None and set(re.findall(r"\\[A-Za-z]+", f.latex)) <= words


def test_multiline_and_single_line():
    cls = REG.get("greek.upsilon_v")
    for i in range(30):
        m = TINY.draw(cls, slot_rng(7, "gen", i), multiline=True)
        s = TINY.draw(cls, slot_rng(7, "gen", i))
        assert m.env == "align*" and "\\\\" in m.latex and "&" in m.latex
        assert s.env == "equation*" and "\\\\" not in s.latex


def test_budget_terminates_on_pathological_table():
    table = _table(
        {
            "start": _rule(("$S = $expr", 1)),
            "start_multiline": _rule(("$S &= $expr", 1)),
            "var": _rule(("x", 1)),
            "expr": _rule(("\\frac{$expr}{$expr}", 3), ("$expr^{$expr}", 3), ("$expr + $expr", 3), ("$expr", 3), ("x", 1)),
        }
    )
    src = GrammarSource({"t": 1}, {"t": table})
    cls = REG.get("greek.upsilon_v")
    for i in range(1000):
        f = src.draw(cls, slot_rng(8, "gen", i))
        assert f is None or (nesting_depth(f.latex) <= 6 and script_count(f.latex) <= 12)


def test_formula_metadata():
    f = TINY.draw(REG.get("greek.nu_v"), slot_rng(9, "gen", 0))
    assert (f.licence, f.authors, f.paper_id, f.paper_version) == ("CC0-1.0", (), None, None)


def test_only_random_is_used(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("unstable RNG primitive used")

    for name in ("choice", "shuffle", "sample", "randint", "randrange"):
        monkeypatch.setattr(random.Random, name, boom)
    assert TINY.draw(REG.get("greek.upsilon_v"), slot_rng(10, "gen", 0)) is not None


def test_shipped_tables_load():
    tables = load_tables()
    assert tuple(tables) == DOMAINS
    assert all(30 <= sum(map(len, t.rules.values())) <= 60 for t in tables.values())


@pytest.mark.parametrize("domain", DOMAINS)
def test_shipped_tables_draw(domain):
    src = GrammarSource({domain: 1})
    for i in range(300):
        cls, level, multi = REG.get(CLASSES[i % 6]), LEVELS[(i // 6) % 3], i % 5 == 0
        f = src.draw(cls, slot_rng(11, domain, i), level=level, multiline=multi)
        assert f is not None, (cls.name, level, multi)
        assert site_level(f.latex, cls.sites(f.latex)[0]) == level
        assert f.env == ("align*" if multi else "equation*")


def test_shipped_tables_are_safe_and_cc0():
    for t in load_tables().values():
        assert t.licence == "CC0-1.0"
        for ps in t.rules.values():
            for p in ps:
                assert check_safe(re.sub(r"\$[A-Za-z_]+", "x", p.rhs)) is None
    for name in ("math", "astro_ph", "physics"):
        from importlib.resources import files

        text = (files("glyphforge.sources.grammar") / "tables" / f"{name}.yaml").read_text("utf-8")
        assert "CC0-1.0" in text.splitlines()[0] and yaml.safe_load(text)["licence"] == "CC0-1.0"
