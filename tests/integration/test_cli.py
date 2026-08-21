"""Testy CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from cli.__main__ import build_parser, main

if TYPE_CHECKING:
    from pathlib import Path


def test_parser_has_all_subcommands() -> None:
    parser = build_parser()
    cmds: set[str] = set()
    for action in parser._actions:  # type: ignore[attr-defined]
        if action.choices:
            cmds.update(action.choices.keys())
    assert {"capture", "collect", "matrix", "override", "serve"} <= cmds


def test_main_help() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])


def test_serve_status() -> None:
    rc = main(["serve", "status"])
    assert rc in (0, 1)


def test_collect_missing_apps(tmp_path: Path) -> None:
    rc = main(["collect", "--apps", str(tmp_path / "missing.json"), "--distros", "fedora"])
    assert rc == 2


def test_collect_dict_apps(tmp_path: Path) -> None:
    apps = tmp_path / "apps.json"
    apps.write_text('{"apps": ["org.kde.kcalc", "org.gimp.GIMP"]}', encoding="utf-8")
    rc = main(["collect", "--apps", str(apps), "--distros", "fedora", "--dry-run"])
    assert rc == 0


def test_collect_list_apps(tmp_path: Path) -> None:
    apps = tmp_path / "apps.json"
    apps.write_text('["org.kde.kcalc"]', encoding="utf-8")
    rc = main(["collect", "--apps", str(apps), "--distros", "flathub", "--dry-run"])
    assert rc == 0


def test_collect_invalid_apps_returns_2(tmp_path: Path) -> None:
    apps = tmp_path / "apps.json"
    apps.write_text('"not a list or dict"', encoding="utf-8")
    rc = main(["collect", "--apps", str(apps), "--distros", "fedora"])
    assert rc == 2


def test_matrix_missing_spec(tmp_path: Path) -> None:
    rc = main(["matrix", "--spec", str(tmp_path / "missing.json")])
    assert rc == 2


def test_matrix_plan(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        '{"apps": ["org.kde.kcalc"], "distros": [{"name": "fedora-kde", "golden_image": "/tmp/x.qcow2"}]}',
        encoding="utf-8",
    )
    rc = main(["matrix", "--spec", str(spec_file)])
    assert rc == 0


def test_override_missing_component(tmp_path: Path) -> None:
    catalog = tmp_path / "fedora.xml.gz"
    catalog.write_bytes(b"<components/>")
    rc = main(
        [
            "override",
            "--id",
            "nonexistent.desktop",
            "--base-url",
            "http://127.0.0.1:8899",
            "--prefix",
            "x",
            "--out",
            str(tmp_path / "out.xml"),
            "--catalog",
            str(catalog),
        ]
    )
    assert rc == 3


def test_matrix_execute_refuses_spec_pinned_dry_run(tmp_path: Path) -> None:
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        '{"apps": ["org.kde.kcalc"], "dry_run": true, '
        '"distros": [{"name": "fedora-kde", "golden_image": "/tmp/x.qcow2"}]}',
        encoding="utf-8",
    )
    rc = main(
        [
            "matrix",
            "--spec",
            str(spec_file),
            "--execute",
            "--backend",
            "fake",
            "--output",
            str(tmp_path / "report.json"),
            "--work-root",
            str(tmp_path / "runs"),
        ]
    )
    assert rc == 2
    assert not (tmp_path / "report.json").exists()


def test_matrix_execute_requires_backend_choice(tmp_path: Path) -> None:
    import json as _json

    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        '{"apps": ["org.kde.kcalc"], "distros": [{"name": "fedora-kde", "golden_image": "/tmp/x.qcow2"}]}',
        encoding="utf-8",
    )
    rc = main(
        [
            "matrix",
            "--spec",
            str(spec_file),
            "--execute",
            "--backend",
            "fake",
            "--output",
            str(tmp_path / "report.json"),
            "--work-root",
            str(tmp_path / "runs"),
        ]
    )
    assert rc == 0
    report = _json.loads((tmp_path / "report.json").read_text())
    assert report["results"]
