"""Testy jednostkowe — shared kernel."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from shared.hashing import sha256_bytes, sha256_file
from shared.pydantic_utils import construct_validated
from shared.results import MatrixReport, PhaseTiming
from shared.types import make_http_url, make_sha256


class TestHashing:
    def test_sha256_bytes(self) -> None:
        assert (
            sha256_bytes(b"hello")
            == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )

    def test_sha256_file(self, tmp_path: Path) -> None:
        f = tmp_path / "x.bin"
        f.write_bytes(b"hello")
        assert sha256_file(f) == sha256_bytes(b"hello")


class TestTypes:
    def test_make_sha256_valid(self) -> None:
        assert make_sha256("a" * 64) == "a" * 64

    def test_make_sha256_invalid_length(self) -> None:
        with pytest.raises(ValueError, match="64 hex"):
            make_sha256("a" * 10)

    def test_make_sha256_invalid_chars(self) -> None:
        with pytest.raises(ValueError, match="64 hex"):
            make_sha256("z" * 64)

    def test_make_http_url_valid(self) -> None:
        assert make_http_url("https://example.com/x.png") == "https://example.com/x.png"
        assert make_http_url("http://127.0.0.1:8899/k.png") == "http://127.0.0.1:8899/k.png"

    def test_make_http_url_invalid(self) -> None:
        with pytest.raises(ValueError, match="http"):
            make_http_url("ftp://example.com/x.png")

    def test_annotated_validates_via_pydantic(self) -> None:
        class M(BaseModel):
            sha: str  # type: ignore[valid-type]
            url: str  # type: ignore[valid-type]

            model_config = {}

        M.model_validate({"sha": "a" * 64, "url": "https://x/"})  # type: ignore[arg-type]


class TestPydanticUtils:
    def test_construct_validated_deterministic(self) -> None:
        class M(BaseModel):
            x: int

        result = construct_validated(M, {"x": 1}, sample_rate=1, seed=42)
        assert result.x == 1

    def test_construct_validated_skip(self) -> None:
        class M(BaseModel):
            x: int = 0

        result = construct_validated(M, {"x": 99}, sample_rate=1000000, seed=1)
        assert result.x == 99


class TestRelativePath:
    def test_relative_path_pydantic(self, tmp_path: Path) -> None:
        from shared.types import RelativePath

        class M(BaseModel):
            path: RelativePath

        M(path=Path("media/x.png"))  # relative OK
        with pytest.raises(ValidationError):
            M(path=tmp_path / "absolute.png")


class TestResultsTiming:
    def _timing(self, phase: str, seconds: float, app: str | None = None) -> PhaseTiming:
        return PhaseTiming(
            distro="fedora-kde",
            app=app,
            phase=phase,
            started_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            seconds=seconds,
        )

    def test_phase_timing_roundtrip_json(self) -> None:
        t = self._timing("create", 1.25, app="org.kde.kcalc")
        t = t.model_copy(update={"detail": {"ok": True, "frames": 3, "note": None}})
        again = PhaseTiming.model_validate_json(t.model_dump_json())
        assert again == t

    def test_phase_timing_rejects_negative_seconds(self) -> None:
        with pytest.raises(ValidationError):
            self._timing("create", -0.1)

    def test_phase_timing_detail_allows_only_json_primitives(self) -> None:
        with pytest.raises(ValidationError):
            PhaseTiming(
                distro="x",
                phase="create",
                started_at=datetime(2026, 8, 21, tzinfo=UTC),
                seconds=0.0,
                detail={"path": Path("/tmp/x")},  # type: ignore[dict-item]
            )

    def test_matrix_report_timings_default_empty_and_totals_empty(self) -> None:
        report = MatrixReport(run_id="r", started_at=datetime(2026, 8, 21, tzinfo=UTC))
        assert report.timings == []
        assert report.phase_totals() == {}

    def test_phase_totals_sums_per_phase_and_derives_boot(self) -> None:
        started = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)
        report = MatrixReport(
            run_id="r",
            started_at=started,
            finished_at=started + timedelta(seconds=10),
            timings=[
                self._timing("create", 1.5),
                self._timing("wait_agent", 2.0),
                self._timing("launch", 0.25, app="a"),
                self._timing("launch", 0.75, app="b"),
                self._timing("verify", 0.5, app="a"),
            ],
        )
        totals = report.phase_totals()
        assert totals["create"] == 1.5
        assert totals["launch"] == 1.0
        assert totals["boot"] == 3.5
        assert totals["run_total"] == 10.0
        assert "wait_session" not in totals
