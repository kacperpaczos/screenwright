"""Testy jednostkowe — visualcheck (część czysta: budowa argv sklepu)."""

from __future__ import annotations

from cli.visualcheck_cmd import build_store_command


def test_template_with_id_placeholder() -> None:
    assert build_store_command("gnome-software --details={id}", "GameConqueror.desktop") == [
        "gnome-software",
        "--details=GameConqueror.desktop",
    ]


def test_template_appends_when_no_placeholder() -> None:
    assert build_store_command("gnome-software --details", "app.desktop") == [
        "gnome-software",
        "--details",
        "app.desktop",
    ]


def test_discover_appstream_uri() -> None:
    assert build_store_command(
        "plasma-discover --application appstream:{id}", "org.kde.kcalc.desktop"
    ) == ["plasma-discover", "--application", "appstream:org.kde.kcalc.desktop"]
