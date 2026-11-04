"""Strict recipe schema (schema_version 1): source, classes, plugins, QC policy, styles, seed, export."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from glyphforge.sources.base import Formula

SCHEMA_VERSION = 1
PACKAGE_RE = r"^[A-Za-z][A-Za-z0-9-]*$"
MODULE_RE = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceSpec(_Model):
    kind: Literal["builtin", "inline", "file"] = "builtin"
    licence: Literal["CC0-1.0", "CC-BY-3.0", "CC-BY-4.0"] | None = None
    formulas: tuple[Formula, ...] = ()
    path: StrictStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _expand_inline(cls, data: Any) -> Any:
        if not isinstance(data, dict) or data.get("kind") != "inline":
            return data
        entries = []
        for e in data.get("formulas") or ():
            e = {"latex": e} if isinstance(e, str) else dict(e)
            if e.setdefault("licence", data.get("licence")) != data.get("licence"):
                raise ValueError("inline formula licence differs from the source licence")
            entries.append(e)
        return {**data, "formulas": entries}

    @model_validator(mode="after")
    def _check_kind(self) -> SourceSpec:
        if self.kind == "builtin" and (self.licence or self.formulas or self.path):
            raise ValueError("builtin source takes no licence, formulas or path")
        if self.kind != "builtin" and not self.licence:
            raise ValueError(f"{self.kind} source requires a licence")
        if self.kind == "inline" and (not self.formulas or self.path):
            raise ValueError("inline source requires formulas and no path")
        if self.kind == "file" and (not self.path or self.formulas):
            raise ValueError("file source requires path and no formulas")
        return self


class StyleSpec(_Model):
    name: StrictStr = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    font: Literal["cm", "lmodern", "mathpazo", "newtx", "libertine", "stix2"]
    size: StrictInt = Field(ge=8, le=12)
    packages: tuple[Annotated[StrictStr, Field(pattern=PACKAGE_RE)], ...] = ()


DEFAULT_STYLES = (
    StyleSpec(name="default", font="cm", size=12),
    StyleSpec(name="cmbright", font="cm", size=12, packages=("cmbright",)),
    StyleSpec(name="libertine", font="libertine", size=12),
)


class QCSpec(_Model):
    ambiguity: Literal["drop", "flag"] = "drop"


class ExportSpec(_Model):
    formats: tuple[Literal["glyphfix"], ...] = ("glyphfix",)


class Recipe(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    seed: StrictInt = Field(default=0, ge=0)
    source: SourceSpec = SourceSpec()
    classes: tuple[StrictStr, ...] | None = None
    plugins: tuple[Annotated[StrictStr, Field(pattern=MODULE_RE)], ...] = ()
    entry_points: StrictBool = False
    qc: QCSpec = QCSpec()
    styles: tuple[StyleSpec, ...] = Field(default=DEFAULT_STYLES, min_length=1)
    export: ExportSpec = ExportSpec()

    @field_validator("styles")
    @classmethod
    def _unique_styles(cls, v: tuple[StyleSpec, ...]) -> tuple[StyleSpec, ...]:
        if len({s.name for s in v}) != len(v):
            raise ValueError("style names must be unique")
        return v
