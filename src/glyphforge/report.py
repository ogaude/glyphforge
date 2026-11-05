"""Post-run diagnostics: scale versus page/crop references (COMP-05) and target/control separability (COMP-06)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import cast

from glyphforge.pixels import PIXEL_POLICY, smart_resize_dims
from glyphforge.render import RENDER_DPI

PAGE_DPI = 400
# (page width px, page height px, paper width pt): 400 DPI renders downscaled to 2048 px on the longest side.
PAGE_REFS = {"a4": (1448, 2048, 595.28), "letter": (1583, 2048, 612.0)}
TRAIN_MAX_PX = 401_408  # glyphfix-math training cap; PIXEL_POLICY["max_px"] (602,112) is the inference-side cap
FLOOR_PX = cast("int", PIXEL_POLICY["min_px"])
_CAPS: dict[str, int] = {"policy": cast("int", PIXEL_POLICY["max_px"]), "train_cap": TRAIN_MAX_PX}


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    s = sorted(values)
    return {f"p{p}": round(s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))], 4) for p in (10, 50, 90)}


def scale_report(rows: Sequence[Mapping], *, corpus: Mapping | None = None) -> dict:
    """Glyph pixels-per-point at the model input per (font, size_pt, structure), against crop and page references."""
    base = RENDER_DPI / 72
    page = {
        name: {cap: round(smart_resize_dims(w, h, FLOOR_PX, mx)[0] / pt, 4) for cap, mx in _CAPS.items()}
        for name, (w, h, pt) in PAGE_REFS.items()
    }
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(f"{r['font']}|{r['size_pt']}|{r['structure']}", []).append(r)
    out_groups, warnings, upsized = {}, [], 0
    for key, grp in sorted(groups.items()):
        ppp: dict[str, list] = {cap: [] for cap in _CAPS}
        ups, tokens = [], []
        for r in grp:
            w, h = r["width"], r["height"]
            for cap, mx in _CAPS.items():
                pw, ph = smart_resize_dims(w, h, FLOOR_PX, mx)
                ppp[cap].append(base * pw / w)
                if cap == "policy":
                    tokens.append(pw * ph // 1024)
                    if w * h < FLOOR_PX:
                        ups.append(pw / w)
        upsized += len(ups)
        med = _quantiles(ppp["train_cap"])["p50"]
        out_groups[key] = {
            "n": len(grp),
            "px_per_pt": {cap: _quantiles(v) for cap, v in ppp.items()},
            "image_tokens": _quantiles(tokens),
            "upsized_share": round(len(ups) / len(grp), 4),
            "mean_upsize": round(sum(ups) / len(ups), 4) if ups else 1.0,
        }
        if med > 2 * page["a4"]["train_cap"]:
            warnings.append(f"{key}: scale gap, median {med:.2f} px/pt vs A4 page {page['a4']['train_cap']:.2f} px/pt (informational)")
    refs: dict = {"crop_300dpi": {"px_per_pt": round(base, 4)}, **{f"page_{n}": v for n, v in page.items()}}
    if corpus is not None:
        refs["corpus"] = dict(corpus)
    return {
        "counts": {"rows": len(rows), "upsized": upsized},
        "flags": {"64-token-min": upsized},
        "groups": out_groups,
        "references": dict(sorted(refs.items())),
        "warnings": warnings,
    }


def _features(row: Mapping) -> tuple[dict, dict]:
    meta = {
        "font": row["font"],
        "size_pt": row["size_pt"],
        "column_cm": row.get("column_cm"),
        "structure": row["structure"],
        "env": row["env"],
        "source": row["source"],
        "site_level": row.get("site_level"),
        "n_tokens": row["n_tokens"] // 16,
        "label_len": len(row["label"]) // 32,
        "error_class": row["error_class"],
    }
    pixel = {"log2_width": int(math.log2(max(1, row["width"]))), "log2_height": int(math.log2(max(1, row["height"])))}
    return meta, pixel


def _tv(a: Counter, b: Counter) -> float:
    na, nb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a[v] / na - b[v] / nb) for v in a.keys() | b.keys())


def balance_report(rows: Sequence[Mapping], *, tv_threshold: float = 0.10, acc_margin: float = 0.05) -> dict:
    """Per-feature TV distance between targets and controls plus leave-one-out joint-key role accuracy.

    Warns when a metadata feature has TV > tv_threshold or the joint-key predictor beats the majority baseline by
    more than acc_margin. Pixel-size features are glyph-dependent and reported as informational only. With one
    matched control per target the warnings mostly fire for r > 1 extra controls and grammar/mutation source imbalance.
    """
    feats = [(_features(r), r["role"] == "target") for r in rows]
    n_t = sum(t for _, t in feats)
    n_c = len(feats) - n_t
    out: dict = {
        "counts": {"targets": n_t, "controls": n_c},
        "thresholds": {"acc_margin": acc_margin, "tv_threshold": tv_threshold},
        "warnings": [],
    }
    if not n_t or not n_c:
        return out | {"tv": {}, "informational": {}, "joint": {}, "accuracy": None, "baseline": None}

    def tv_table(idx: int) -> dict:
        return {
            k: round(_tv(Counter(str(f[idx][k]) for f, t in feats if t), Counter(str(f[idx][k]) for f, t in feats if not t)), 4)
            for k in sorted(feats[0][0][idx])
        }

    tv, info = tv_table(0), tv_table(1)
    out["warnings"] += [f"{k} separates targets from controls (TV {v:.2f} > {tv_threshold:.2f})" for k, v in tv.items() if v > tv_threshold]
    keys = [tuple(sorted((k, str(v)) for k, v in f[0].items())) for f, _ in feats]
    seen: dict = {}
    for key, (_, t) in zip(keys, feats, strict=True):
        seen.setdefault(key, Counter())[t] += 1
    hits = 0
    for key, (_, t) in zip(keys, feats, strict=True):
        c = seen[key].copy()
        c[t] -= 1
        pred = (n_t >= n_c) if c[True] == c[False] else c[True] > c[False]
        hits += pred == t
    acc, baseline = hits / len(feats), max(n_t, n_c) / len(feats)
    if acc > baseline + acc_margin:
        out["warnings"].append(f"joint metadata predicts role (accuracy {acc:.2f} > baseline {baseline:.2f} + {acc_margin:.2f})")
    joint: dict = {}
    for f, t in feats:
        m = f[0]
        cell = joint.setdefault(f"{m['error_class']}|{m['font']}|{m['size_pt']}|{m['structure']}", {"controls": 0, "targets": 0})
        cell["targets" if t else "controls"] += 1
    return out | {
        "tv": tv,
        "informational": info,
        "joint": dict(sorted(joint.items())),
        "accuracy": round(acc, 4),
        "baseline": round(baseline, 4),
    }
