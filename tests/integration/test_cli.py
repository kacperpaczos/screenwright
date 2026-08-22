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
    assert {"capture", "collect", "override", "serve"} <= cmds


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
