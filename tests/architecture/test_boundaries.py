"""Testy architektury — granice domen."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ["corpus", "capture", "override", "matrix", "verification"]
SHARED = ROOT / "shared"
DOMAIN_DIRS = [ROOT / "domains" / d for d in DOMAINS]


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None


def _imports_from_other_domains(tree: ast.Module, own_domain: str) -> list[tuple[str, int]]:
    bad: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            module = node.module
            for d in DOMAINS:
                if d == own_domain:
                    continue
                if module == f"domains.{d}" or module.startswith(f"domains.{d}."):
                    bad.append((module, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for d in DOMAINS:
                    if d == own_domain:
                        continue
                    if alias.name == f"domains.{d}" or alias.name.startswith(f"domains.{d}."):
                        bad.append((alias.name, node.lineno))
    return bad


def test_domains_do_not_import_each_other() -> None:
    """Każdy domains/<x> może importować wyłącznie z shared/, nie z innych domains/."""
    violations: list[str] = []
    for d in DOMAINS:
        for py in (ROOT / "domains" / d).rglob("*.py"):
            tree = _parse(py)
            if tree is None:
                continue
            imports = _imports_from_other_domains(tree, d)
            for module, lineno in imports:
                violations.append(f"{py.relative_to(ROOT)}:{lineno} imports {module}")
    assert not violations, "\n".join(violations)


def test_shared_does_not_import_domains() -> None:
    """shared/ jest shared kernel — NIE może importować z domains/."""
    violations: list[str] = []
    for py in SHARED.rglob("*.py"):
        tree = _parse(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module.startswith("domains"):
                    violations.append(f"{py.relative_to(ROOT)}:{node.lineno} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("domains"):
                        violations.append(
                            f"{py.relative_to(ROOT)}:{node.lineno} imports {alias.name}"
                        )
    assert not violations, "\n".join(violations)
