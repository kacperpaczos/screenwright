"""Walidacja modeli pydantic — round-trip JSON Schema."""

from __future__ import annotations

import importlib
import pkgutil

from domains.capture import models as capture_models
from domains.corpus import models as corpus_models
from domains.matrix import models as matrix_models
from shared import results as shared_results


def _all_pydantic_models(module) -> list[type]:
    from pydantic import BaseModel

    found: list[type] = []
    for _, name, _ in pkgutil.iter_modules([module.__path__[0]]):
        sub = importlib.import_module(f"{module.__name__}.{name}")
        for attr_name in dir(sub):
            attr = getattr(sub, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
                found.append(attr)
    return found


def test_corpus_models_have_json_schema() -> None:

    found = [
        corpus_models.CorpusEntry,
        corpus_models.CorpusIndex,
    ]
    for model in found:
        schema = model.model_json_schema()
        assert "properties" in schema


def test_capture_models_have_json_schema() -> None:

    found = [
        capture_models.CaptureSpec,
        capture_models.CaptureResult,
        capture_models.WindowInfo,
        capture_models.FrameDigest,
    ]
    for model in found:
        schema = model.model_json_schema()
        assert "properties" in schema


def test_matrix_models_have_json_schema() -> None:
    found = [
        matrix_models.DistroSpec,
        matrix_models.DomainConfig,
        matrix_models.MatrixRunSpec,
        matrix_models.MatrixStep,
    ]
    for model in found:
        schema = model.model_json_schema()
        assert "properties" in schema


def test_shared_results_have_json_schema() -> None:
    found = [
        shared_results.Score,
        shared_results.VerificationResult,
        shared_results.MatrixReport,
        shared_results.ScreenshotHash,
    ]
    for model in found:
        schema = model.model_json_schema()
        assert "properties" in schema


def run() -> None:
    test_corpus_models_have_json_schema()
    test_capture_models_have_json_schema()
    test_matrix_models_have_json_schema()
    test_shared_results_have_json_schema()
