"""Shared kernel — typy wyników używane przez wiele domen."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.types import Sha256


class Score(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0.0, le=1.0)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: Score
    threshold: Score
    location: tuple[int, int] | None = None
    expected_template: Path
    actual_screenshot: Path
    notes: str | None = None

    @model_validator(mode="after")
    def _passed_iff_above_threshold(self) -> "VerificationResult":
        expected = self.score.value >= self.threshold.value
        if self.passed != expected:
            raise ValueError(
                f"passed={self.passed} inconsistent with "
                f"score={self.score.value} vs threshold={self.threshold.value}"
            )
        return self


_BOOT_PHASES = ("create", "wait_agent", "wait_session", "warm_restore")
"""Fazy składające się na „boot" w `MatrixReport.phase_totals()`.

`create` to zimny start domeny, `warm_restore` — przywrócenie ze stanu; po obu
następuje czekanie na agenta i sesję. Suma daje czas od „chcę maszynę" do
„mogę w niej klikać" niezależnie od ścieżki.
"""


class PhaseTiming(BaseModel):
    """Jedna zmierzona faza przebiegu: co, dla kogo, ile trwało.

    `detail` trzyma tylko prymitywy JSON (bez `Path`), żeby raport dało się
    porównać plik do pliku między przebiegami. `ok=False` oznacza, że faza
    skończyła się wyjątkiem — czas i tak jest zapisany, bo porażka po 60 s
    czekania to inna informacja niż porażka po 0.1 s.
    """

    model_config = ConfigDict(extra="forbid")

    distro: str
    app: str | None = None
    phase: str = Field(min_length=1)
    started_at: datetime
    seconds: float = Field(ge=0.0)
    detail: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class MatrixReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    results: list[VerificationResult] = Field(default_factory=list)
    timings: list[PhaseTiming] = Field(default_factory=list)

    def phase_totals(self) -> dict[str, float]:
        """Suma sekund per faza + pochodne `boot` i `run_total`.

        `boot` sumuje `_BOOT_PHASES` (tylko te, które wystąpiły); `run_total`
        to ściana zegara całego przebiegu — różnica między nim a sumą faz to
        narzut runnera, którego nie mierzymy osobno.
        """
        totals: dict[str, float] = {}
        for t in self.timings:
            totals[t.phase] = totals.get(t.phase, 0.0) + t.seconds
        boot = [totals[p] for p in _BOOT_PHASES if p in totals]
        if boot:
            totals["boot"] = sum(boot)
        if self.finished_at is not None:
            totals["run_total"] = (self.finished_at - self.started_at).total_seconds()
        return totals


class ScreenshotHash(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: Sha256
    captured_at: datetime


__all__ = [
    "MatrixReport",
    "PhaseTiming",
    "Score",
    "ScreenshotHash",
    "VerificationResult",
]
