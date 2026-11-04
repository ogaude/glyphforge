"""Formula supply contract: the runtime formula record and the Source protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from glyphforge.canon.label import MAX_LABEL_CHARS, structural_problems
from glyphforge.canon.safety import check_render

LICENSES: dict[str, str] = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
}
ENVS = ("equation*", "align*", "gather*")


class Formula(BaseModel):
    """One source formula with its licence and, for CC BY material, the attribution fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    latex: StrictStr
    licence: StrictStr
    env: StrictStr = "equation*"
    paper_id: StrictStr | None = None
    paper_version: StrictStr | None = None
    authors: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Formula:
        if self.licence not in LICENSES:
            raise ValueError(f"licence {self.licence!r} not allowed; expected one of {tuple(LICENSES)}")
        if self.env not in ENVS:
            raise ValueError(f"env {self.env!r} not allowed; expected one of {ENVS}")
        if len(self.latex) > MAX_LABEL_CHARS:
            raise ValueError(f"formula longer than {MAX_LABEL_CHARS} characters")
        if (reason := check_render(self.latex)) is not None:
            raise ValueError(f"formula rejected by the render filter: {reason}")
        if problems := structural_problems(self.latex):
            raise ValueError(f"formula is structurally invalid: {problems}")
        if self.licence.startswith("CC-BY"):
            missing = [k for k in ("paper_id", "paper_version") if not getattr(self, k)] + ([] if self.authors else ["authors"])
            if missing:
                raise ValueError(f"CC BY formula requires attribution fields: {missing}")
        return self


@runtime_checkable
class Source(Protocol):
    """Anything that supplies formulas to the pipeline."""

    def formulas(self) -> Sequence[Formula]: ...
