"""CLI: visualcheck — dowód wizualny cel 2 (boot → override → zrzut → match).

Produkcyjna wersja harnessu, którym zweryfikowano cel 2 na GNOME Software i KDE
Discover (`docs/override-deploy.md`). Boot overlay na golden, podmiana zrzutu w
katalogu (`patch_catalog`), otwarcie sklepu w sesji, `virsh screenshot` i sprawdzenie
markera (`domains.verification.store_shows_marker`). Używa prymitywów
`domains.matrix.backend`/`guest` — one dlatego zostają po retirementcie silnika.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from domains.matrix.backend.ssh import SshShell
from domains.matrix.backend.virsh import VirshBackend
from domains.matrix.guest import (
    GuestWaits,
    wait_for_agent,
    wait_for_session,
    wait_for_shell,
)
from domains.override.catalog import GzipXmlCatalogLoader, patch_catalog
from domains.override.models import OverrideSpec
from domains.verification.visual import store_shows_marker
from shared.logging import log_entry

if TYPE_CHECKING:
    import argparse

# Serwer mediów jako PLIK — nie inline `python3 -c`: SSH skleja argv w string i
# zdalny shell go re-tokenizuje, więc skrypt ze spacjami się rozjeżdża.
_MEDIA_SERVER_PY = (
    "import http.server, socketserver, os, sys\n"
    "os.chdir('/var/tmp/swmedia')\n"
    "port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080\n"
    "socketserver.TCPServer(('127.0.0.1', port),"
    " http.server.SimpleHTTPRequestHandler).serve_forever()\n"
)


def build_store_command(template: str, component_id: str) -> list[str]:
    """Buduje argv otwarcia sklepu. ``{id}`` w szablonie → component_id; brak → doklejany.

    Np. 'gnome-software --details={id}' albo 'plasma-discover --application appstream:{id}'.
    """
    text = template.format(id=component_id) if "{id}" in template else f"{template} {component_id}"
    return text.split()


def _ssh_base(port: int, key: Path) -> list[str]:
    return [
        "-i",
        str(key),
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "ConnectTimeout=15",
    ]


def run_visualcheck(args: argparse.Namespace) -> int:
    golden = Path(args.golden)
    media_dir = Path(args.media_dir)
    marker = Path(args.marker) if args.marker else media_dir / f"{args.prefix}-source.png"
    key = Path(args.key)
    port = int(args.ssh_port)
    name = args.name
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    disk = work / f"{name}.qcow2"
    out = Path(args.out)
    backend = VirshBackend(args.libvirt_uri)
    shell = SshShell(port=port, user=args.user, key=key)
    base = _ssh_base(port, key)

    def ssh(argv: list[str], timeout: float = 180) -> tuple[str, int]:
        try:
            r = subprocess.run(
                ["ssh", *base, "-p", str(port), f"{args.user}@127.0.0.1", "--", *argv],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            return "TIMEOUT", 124

    def scp_to(src: Path, dst: str) -> None:
        subprocess.run(
            ["scp", *base, "-P", str(port), str(src), f"{args.user}@127.0.0.1:{dst}"],
            capture_output=True,
        )

    def scp_from(src: str, dst: Path) -> None:
        subprocess.run(
            ["scp", *base, "-P", str(port), f"{args.user}@127.0.0.1:{src}", str(dst)],
            capture_output=True,
        )

    def cleanup() -> None:
        subprocess.run(["virsh", "-c", args.libvirt_uri, "destroy", name], capture_output=True)
        subprocess.run(["virsh", "-c", args.libvirt_uri, "undefine", name], capture_output=True)

    cleanup()
    disk.unlink(missing_ok=True)
    backend.create_overlay(golden, disk)
    net = (
        f"user,backend.type=passt,portForward0.proto=tcp,portForward0.address=127.0.0.1,"
        f"portForward0.range0.start={port},portForward0.range0.to=22"
    )
    vi = subprocess.run(
        [
            "virt-install",
            "--connect",
            args.libvirt_uri,
            "--name",
            name,
            "--memory",
            str(args.memory),
            "--vcpus",
            "2",
            "--import",
            "--disk",
            f"path={disk},format=qcow2,bus=virtio",
            "--network",
            net,
            "--osinfo",
            f"name={args.osinfo}",
            "--graphics",
            "vnc,listen=127.0.0.1",
            "--noautoconsole",
            "--wait",
            "0",
        ],
        capture_output=True,
        text=True,
    )
    if vi.returncode != 0:
        log_entry(40, "visualcheck.virt_install_failed", err=(vi.stderr or vi.stdout)[-300:])
        cleanup()
        return 4
    try:
        waits = GuestWaits()
        wait_for_agent(backend, name, waits=waits)
        wait_for_shell(shell, waits=waits)
        try:
            wait_for_session(shell, waits=waits)
        except Exception as exc:
            log_entry(30, "visualcheck.session_wait_warn", error=str(exc)[:120])

        # media do gościa + serwer jako jednostka systemd
        ssh(["sudo", "mkdir", "-p", "/var/tmp/swmedia"])
        ssh(["sudo", "chmod", "777", "/var/tmp/swmedia"])
        for png in sorted(media_dir.glob(f"{args.prefix}-*.png")):
            scp_to(png, f"/var/tmp/swmedia/{png.name}")
        server_py = work / "sw_media_server.py"
        server_py.write_text(_MEDIA_SERVER_PY)
        scp_to(server_py, "/tmp/sw_media_server.py")
        ssh(["sudo", "cp", "/tmp/sw_media_server.py", "/var/tmp/sw_media_server.py"])
        ssh(["sudo", "systemctl", "reset-failed", "swmedia"])
        ssh(
            [
                "sudo",
                "systemd-run",
                "--unit=swmedia",
                "--collect",
                "--",
                "python3",
                "/var/tmp/sw_media_server.py",
                str(args.media_port),
            ]
        )
        time.sleep(2)
        selftest, _ = ssh(
            [
                "curl",
                "-sS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                f"http://127.0.0.1:{args.media_port}/{args.prefix}-source.png",
            ]
        )
        log_entry(20, "visualcheck.media_selftest", http_code=selftest.strip())

        # pull katalog → patch naszym kodem → push → refresh
        scp_from(args.catalog, work / "catalog.gz")
        patch_catalog(
            OverrideSpec(
                component_id=args.component_id,
                base_url=f"http://127.0.0.1:{args.media_port}",
                prefix=args.prefix,
                out=work / "catalog-patched.gz",
                priority=1,  # nieużywane przez patch_catalog, ale wymagane przez model
                catalog_paths=[work / "catalog.gz"],
            ),
            loader=GzipXmlCatalogLoader(),
        )
        scp_to(work / "catalog-patched.gz", "/tmp/catalog-patched.gz")
        ssh(["sudo", "cp", "/tmp/catalog-patched.gz", args.catalog])
        ssh(["sudo", "appstreamcli", "refresh", "--force"])
        ssh(["appstreamcli", "refresh", "--force"])

        # pełny reset sklepu + otwarcie strony aplikacji w sesji.
        # Uwaga: SSH skleja argv i re-tokenizuje w zdalnym shellu, więc żaden
        # pojedynczy argument nie może zawierać spacji ani `~` do rozwinięcia —
        # ścieżki podajemy absolutnie, bez `bash -c`.
        home = f"/home/{args.user}"
        ssh(["gnome-software", "--quit"])
        ssh(["pkill", "-u", args.user, "-9", "gnome-software"])
        time.sleep(2)
        ssh(["rm", "-rf", f"{home}/.cache/gnome-software", f"{home}/.local/share/gnome-software"])
        store_argv = build_store_command(args.store_cmd, args.component_id)
        ssh(["systemd-run", "--user", "--collect", "--quiet", *store_argv])

        best = 0.0
        t_open = time.monotonic()
        for wait_s in (18, 32, 48, 66, 88):
            while time.monotonic() - t_open < wait_s:
                time.sleep(2)
            subprocess.run(
                [
                    "virsh",
                    "-c",
                    args.libvirt_uri,
                    "send-key",
                    name,
                    "--codeset",
                    "linux",
                    "KEY_ESC",
                ],
                capture_output=True,
            )
            time.sleep(1)
            backend.screenshot(name, out)
            ok, frac = store_shows_marker(out, marker, threshold=args.threshold)
            best = max(best, frac)
            log_entry(20, "visualcheck.poll", after_open_s=wait_s, marker_fraction=frac)
            if ok:
                break
        renders = best >= args.threshold
        log_entry(
            20 if renders else 40,
            "visualcheck.result",
            component=args.component_id,
            marker_fraction=best,
            renders_ours=renders,
            screenshot=str(out),
        )
        return 0 if renders else 3
    finally:
        cleanup()
