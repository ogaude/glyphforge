"""Strict recipe schema (schema_version 3): sources, classes, plugins, QC, typography, structure, composition, bounds, render, export."""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from glyphforge.sources.base import Formula

SCHEMA_VERSION = 3
PACKAGE_RE = r"^[A-Za-z][A-Za-z0-9-]*$"
MODULE_RE = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"


FONT = Literal["cm", "lmodern", "mathpazo", "newtx", "libertine", "stix2"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@cache
def _typography_defaults() -> dict[str, dict]:
    raw = yaml.safe_load(Path(__file__).with_name("typography.yaml").read_text(encoding="utf-8"))
    return {k: {kk: float(v) for kk, v in m.items()} for k, m in raw.items()}


def _typo_default(key: str):
    return lambda: {(int(k) if key == "sizes" else k): v for k, v in _typography_defaults()[key].items()}


def _check_weights(name: str, mapping: Mapping[Any, float] | None) -> Mapping[Any, float] | None:
    if mapping is not None and (any(w < 0 for w in mapping.values()) or not any(w > 0 for w in mapping.values())):
        raise ValueError(f"{name} weights must be non-negative with at least one positive")
    return mapping


class SourceSpec(_Model):
    kind: Literal["builtin", "inline", "file", "grammar", "mutation", "mix"] = "builtin"
    licence: Literal["CC0-1.0", "CC-BY-3.0", "CC-BY-4.0"] | None = None
    formulas: tuple[Formula, ...] = ()
    path: StrictStr | None = None
    domains: dict[Literal["math", "astro-ph", "physics"], float] | None = None
    sha256: StrictStr | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_sites: StrictInt | None = Field(default=None, ge=1, le=3)
    parts: tuple[SourceSpec, ...] = ()
    shares: tuple[float, float] | None = None

    @model_validator(mode="before")
    @classmethod
    def _expand(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("kind") == "mix" and data.get("shares") is None:
            kinds = [p.get("kind") if isinstance(p, dict) else p.kind for p in data.get("parts") or ()]
            if len(kinds) == 2 and set(kinds) == {"grammar", "mutation"}:
                data = {**data, "shares": (0.3, 0.7) if kinds[0] == "grammar" else (0.7, 0.3)}
        if data.get("kind") != "inline":
            return data
        entries = []
        for e in data.get("formulas") or ():
            e = {"latex": e} if isinstance(e, str) else dict(e)
            if e.setdefault("licence", data.get("licence")) != data.get("licence"):
                raise ValueError("inline formula licence differs from the source licence")
            entries.append(e)
        return {**data, "formulas": entries}

    @field_validator("domains")
    @classmethod
    def _domain_weights(cls, v):
        return _check_weights("domains", v)

    @model_validator(mode="after")
    def _check_kind(self) -> SourceSpec:
        k = self.kind
        if k in ("builtin", "grammar", "mutation", "mix") and self.licence:
            raise ValueError(f"{k} source takes no licence")
        if k not in ("builtin", "grammar", "mutation", "mix") and not self.licence:
            raise ValueError(f"{k} source requires a licence")
        if (self.domains is not None and k != "grammar") or ((self.sha256 or self.max_sites) and k != "mutation"):
            raise ValueError(f"{k} source takes no domains, sha256 or max_sites")
        if (self.parts or self.shares) and k != "mix":
            raise ValueError(f"{k} source takes no parts or shares")
        if self.path and k not in ("file", "mutation"):
            raise ValueError(f"{k} source takes no path")
        if self.formulas and k != "inline":
            raise ValueError(f"{k} source takes no formulas")
        if k == "inline" and (not self.formulas or self.path):
            raise ValueError("inline source requires formulas and no path")
        if k == "file" and (not self.path or self.formulas):
            raise ValueError("file source requires path and no formulas")
        if k == "mutation" and not (self.path and self.sha256):
            raise ValueError("mutation source requires path and sha256")
        if k == "mix":
            if len(self.parts) != 2 or any(p.kind == "mix" for p in self.parts):
                raise ValueError("mix source requires exactly 2 non-mix parts")
            if self.shares is None:
                raise ValueError("mix shares required")
            if not all(0 < x < 1 for x in self.shares) or abs(sum(self.shares) - 1) > 1e-9:
                raise ValueError("mix shares must be in (0, 1) and sum to 1")
        return self


SourceSpec.model_rebuild()


class StyleSpec(_Model):
    name: StrictStr = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    font: FONT
    size: StrictInt = Field(ge=8, le=12)
    packages: tuple[Annotated[StrictStr, Field(pattern=PACKAGE_RE)], ...] = ()
    weight: float = Field(default=1.0, gt=0)


DEFAULT_STYLES = (
    StyleSpec(name="default", font="cm", size=12),
    StyleSpec(name="cmbright", font="cm", size=12, packages=("cmbright",)),
    StyleSpec(name="libertine", font="libertine", size=12),
)


class TypographySpec(_Model):
    fonts: dict[FONT, float] = Field(default_factory=_typo_default("fonts"))
    sizes: dict[int, float] = Field(default_factory=_typo_default("sizes"))
    site_levels: dict[Literal["base", "script", "scriptscript"], float] = Field(default_factory=_typo_default("site_levels"))
    packages: tuple[Annotated[StrictStr, Field(pattern=PACKAGE_RE)], ...] = ()

    @field_validator("fonts", "sizes", "site_levels")
    @classmethod
    def _weights(cls, v, info):
        if info.field_name == "sizes" and any(not 8 <= k <= 12 for k in v):
            raise ValueError("size keys must be in 8..12")
        return _check_weights(info.field_name, v)


class StructureSpec(_Model):
    kinds: dict[Literal["display", "inline", "numbered"], float] = {"display": 1.0, "inline": 0.0, "numbered": 0.0}
    column_cm: dict[float, float] = Field(default_factory=_typo_default("column_cm"))
    multiline: float = Field(default=0.2, ge=0, le=1)
    punct_prob: float = Field(default=0.2, ge=0, le=1)
    text_prob: float = Field(default=0.8, ge=0, le=1)

    @field_validator("kinds", "column_cm")
    @classmethod
    def _weights(cls, v, info):
        if info.field_name == "column_cm" and any(not 5 <= k <= 30 for k in v):
            raise ValueError("column_cm keys must be in [5, 30]")
        return _check_weights(info.field_name, v)


class CompositionSpec(_Model):
    total: StrictInt = Field(default=100, ge=1)
    shares: dict[StrictStr, float] | None = None
    hard_negative_ratio: float = Field(default=1.0, ge=1.0)
    attempt_cap: StrictInt = Field(default=5, ge=1, le=20)

    @field_validator("shares")
    @classmethod
    def _shares(cls, v):
        if v is not None and (any(x < 0 for x in v.values()) or abs(sum(v.values()) - 1) > 1e-9):
            raise ValueError("shares must be non-negative and sum to 1")
        return v


class BoundsSpec(_Model):
    max_tokens: StrictInt = Field(default=500, ge=16, le=4096)
    token_margin: StrictInt = Field(default=60, ge=0)
    max_depth: StrictInt = Field(default=6, ge=1, le=32)
    max_scripts: StrictInt = Field(default=12, ge=0, le=64)

    @model_validator(mode="after")
    def _margin(self) -> BoundsSpec:
        if self.token_margin >= self.max_tokens:
            raise ValueError("token_margin must be below max_tokens")
        return self

    @property
    def token_cap(self) -> int:
        return self.max_tokens - self.token_margin


class RenderSpec(_Model):
    pad_px: StrictInt = Field(default=0, ge=0, le=64)


class QCSpec(_Model):
    ambiguity: Literal["drop", "flag"] = "drop"


class BlocklistPin(_Model):
    path: StrictStr
    sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class OpSpec(_Model):
    p: float = Field(default=0.5, ge=0, le=1)
    min: float | None = None
    max: float | None = None


# Fixed application order; units: contrast factor (1 = unchanged), rotate degrees (magnitude), blur/noise sigma, jpeg quality.
DEGRADE_OPS = ("contrast", "rotate", "blur", "noise", "jpeg")
DEGRADE_DEFAULTS = {"contrast": (0.7, 1.0), "rotate": (0.0, 1.5), "blur": (0.3, 0.8), "noise": (1.0, 4.0), "jpeg": (60.0, 95.0)}
DEGRADE_CAPS = {"contrast": (0.5, 1.0), "rotate": (0.0, 3.0), "blur": (0.0, 1.5), "noise": (0.0, 8.0), "jpeg": (40.0, 100.0)}


class DegradeSpec(_Model):
    clean_share: float = Field(default=0.0, ge=0, le=1)
    contrast: OpSpec | None = None
    rotate: OpSpec | None = None
    blur: OpSpec | None = None
    noise: OpSpec | None = None
    jpeg: OpSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def _fill(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for op in DEGRADE_OPS:
            if isinstance(given := out.get(op), OpSpec):  # a Python caller's instance gets the same defaults and cap errors as a YAML dict
                given = given.model_dump(exclude_none=True)
            if isinstance(given, dict):
                out[op] = {"min": DEGRADE_DEFAULTS[op][0], "max": DEGRADE_DEFAULTS[op][1]} | {k: v for k, v in given.items() if v is not None}
        return out

    @model_validator(mode="after")
    def _caps(self) -> DegradeSpec:
        for op in DEGRADE_OPS:
            if (s := getattr(self, op)) is None:
                continue
            lo, hi = DEGRADE_CAPS[op]
            if not lo <= s.min <= s.max <= hi:
                raise ValueError(f"degrade.{op}: range [{s.min}, {s.max}] outside cap [{lo}, {hi}]")
        return self


class ExportSpec(_Model):
    formats: tuple[Literal["glyphfix", "parquet"], ...] = ()
    blocklist: BlocklistPin | None = None
    shard_mb: StrictInt = Field(default=500, ge=1, le=4096)
    row_group_rows: StrictInt = Field(default=1000, ge=1, le=100_000)
    degrade: DegradeSpec | None = None

    @model_validator(mode="after")
    def _gate(self) -> ExportSpec:
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("export.formats must be unique")
        if self.formats and self.blocklist is None:
            raise ValueError("export.formats needs export.blocklist (path + sha256): the leak gate has no skip")
        return self


class Recipe(_Model):
    schema_version: Literal[3] = SCHEMA_VERSION
    seed: StrictInt = Field(default=0, ge=0)
    source: SourceSpec = SourceSpec()
    classes: tuple[StrictStr, ...] | None = None
    plugins: tuple[Annotated[StrictStr, Field(pattern=MODULE_RE)], ...] = ()
    entry_points: StrictBool = False
    qc: QCSpec = QCSpec()
    styles: tuple[StyleSpec, ...] | None = Field(default=None, min_length=1)
    typography: TypographySpec = TypographySpec()
    structure: StructureSpec = StructureSpec()
    composition: CompositionSpec = CompositionSpec()
    bounds: BoundsSpec = BoundsSpec()
    render: RenderSpec = RenderSpec()
    export: ExportSpec = ExportSpec()

    @field_validator("styles")
    @classmethod
    def _unique_styles(cls, v: tuple[StyleSpec, ...] | None) -> tuple[StyleSpec, ...] | None:
        if v is not None and len({s.name for s in v}) != len(v):
            raise ValueError("style names must be unique")
        return v
