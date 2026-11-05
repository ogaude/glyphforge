"""Export-time, seeded image degradation, applied only to clean QC-passed crops (numpy RNG is used for the noise array only)."""

from __future__ import annotations

import io
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageFilter

from glyphforge.recipe.schema import DEGRADE_OPS, DegradeSpec
from glyphforge.rng import slot_rng
from glyphforge.store import png_bytes

_FIELD = {"contrast": "c", "rotate": "deg", "blur": "sigma", "noise": "sigma", "jpeg": "quality"}


def degrade_ops(spec: DegradeSpec | None, seed: int, key: str) -> list[dict]:
    """Ordered ``{"op", ...params}`` list for ``key``; ``[]`` means leave the image clean.

    Minimal-pair rows must share ``key`` (the pair_id) so both rows get identical ops; unpaired extras use their sample_id.
    Every op consumes exactly four ``random()`` draws (apply, strength, sign, aux) whether or not it applies, so changing one op's
    probability never shifts another op's parameters.
    """
    if spec is None:
        return []
    rng = slot_rng(seed, "degrade", key)
    clean = rng.random() < spec.clean_share
    ops: list[dict] = []
    for name in DEGRADE_OPS:
        roll, strength, sign, aux = (rng.random() for _ in range(4))
        op = getattr(spec, name)
        if clean or op is None or roll >= op.p:
            continue
        value = op.min + strength * (op.max - op.min)
        if name == "jpeg":
            ops.append({"op": name, "quality": round(value)})
            continue
        entry = {"op": name, _FIELD[name]: round(-value if name == "rotate" and sign < 0.5 else value, 4)}
        if name == "noise":
            entry["seed"] = int(aux * 2**63)
        ops.append(entry)
    return ops


def apply_ops(png: bytes, ops: Sequence[dict]) -> bytes:
    """Apply ``ops`` in list order and re-encode deterministically; an empty list returns ``png`` unchanged."""
    if not ops:
        return png
    img: Image.Image = Image.open(io.BytesIO(png))
    if img.mode != "L":
        raise ValueError(f"expected a grayscale PNG, got mode {img.mode}")
    img.load()
    for op in ops:
        match op["op"]:
            case "contrast":
                img = Image.fromarray(np.rint(255 - (255 - np.asarray(img, dtype=np.float64)) * op["c"]).astype(np.uint8))
            case "rotate":
                img = img.rotate(op["deg"], resample=Image.BICUBIC, expand=True, fillcolor=255)  # type: ignore[attr-defined]
            case "blur":
                img = img.filter(ImageFilter.GaussianBlur(op["sigma"]))
            case "noise":
                arr = np.asarray(img, dtype=np.float64)
                noise = np.random.Generator(np.random.PCG64(op["seed"])).normal(0, op["sigma"], arr.shape)
                img = Image.fromarray(np.clip(np.rint(arr + noise), 0, 255).astype(np.uint8))
            case "jpeg":
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=op["quality"])
                img = Image.open(buf).convert("L")
            case other:
                raise ValueError(f"unknown degrade op {other!r}")
    return png_bytes(np.asarray(img, dtype=np.uint8))
