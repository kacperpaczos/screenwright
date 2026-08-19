"""CLI subcommand: vm — operacje operatorskie na domenach libvirt.

Podkomendy:
- ``vm ssh <name> [-- command args...]`` — SSH do VM Ubuntu (klucz, auto-IP).
- ``vm view <name>`` — otwórz virt-viewer na domenie.
- ``vm snapshot <name> <out.png>`` — ``virsh screenshot <name> <out>`` (PNG z virtio-gpu).
- ``vm diagnose <name> [--output PATH|--print]`` — diagnostyka snap-store w VM.

Wszystkie komendy są cienkimi wrapperami na istniejące skrypty
``vm/scripts/*.sh`` i ``virsh`` — logika specyficzna dla VM Ubuntu.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from shared.logging import log_entry
from shared.settings import DEFAULT_LIBVIRT_URI

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _ROOT / "vm" / "scripts"


def _script_path(name: str) -> Path:
    path = _SCRIPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"vm script not found: {path}")
    return path


def run_vm_ssh(args: argparse.Namespace) -> int:
    """SSH do VM Ubuntu (wrapper na vm/scripts/ubuntu-ssh.sh)."""
    cmd = [str(_script_path("ubuntu-ssh.sh")), args.name, *args.ssh_args]
    log_entry(20, "cli.vm.ssh", domain=args.name)
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def run_vm_view(args: argparse.Namespace) -> int:
    """virt-viewer na działającej domenie (VNC)."""
    if shutil.which("virt-viewer") is None:
        print("virt-viewer nie znaleziony w PATH (dnf install virt-viewer)", file=sys.stderr)
        return 1
    log_entry(20, "cli.vm.view", domain=args.name)
    proc = subprocess.run(["virt-viewer", "-c", DEFAULT_LIBVIRT_URI, args.name], check=False)
    return proc.returncode


def run_vm_snapshot(args: argparse.Namespace) -> int:
    """``virsh screenshot <name> <out>`` — framebuffer dump."""
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_entry(20, "cli.vm.snapshot", domain=args.name, output=str(out_path))
    proc = subprocess.run(
        ["virsh", "-c", DEFAULT_LIBVIRT_URI, "screenshot", args.name, str(out_path)],
        check=False,
    )
    return proc.returncode


def run_vm_diagnose(args: argparse.Namespace) -> int:
    """vm/scripts/diagnose-ubuntu.sh — diagnostyka snap-store w VM."""
    cmd = [str(_script_path("diagnose-ubuntu.sh")), args.name]
    if args.print:
        cmd.append("--print")
    if args.output:
        cmd.extend(["--output", str(args.output)])
    log_entry(20, "cli.vm.diagnose", domain=args.name, output=args.output)
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def add_vm_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_vm = sub.add_parser("vm", help="operacje operatorskie na domenach libvirt")
    vm_sub = p_vm.add_subparsers(dest="vm_action", required=True)

    p_ssh = vm_sub.add_parser("ssh", help="SSH do VM Ubuntu (klucz, auto-IP)")
    p_ssh.add_argument("name", help="nazwa domeny libvirt (np. sw-ubuntu-xxxx)")
    p_ssh.add_argument(
        "ssh_args",
        nargs=argparse.REMAINDER,
        help="argumenty przekazywane do ssh (np. -- snap version)",
    )
    p_ssh.set_defaults(func=run_vm_ssh)

    p_view = vm_sub.add_parser("view", help="virt-viewer na domenie")
    p_view.add_argument("name")
    p_view.set_defaults(func=run_vm_view)

    p_snap = vm_sub.add_parser("snapshot", help="virsh screenshot do PNG")
    p_snap.add_argument("name")
    p_snap.add_argument("output", help="ścieżka wyjściowa PNG")
    p_snap.set_defaults(func=run_vm_snapshot)

    p_diag = vm_sub.add_parser("diagnose", help="diagnostyka snap-store w VM")
    p_diag.add_argument("name")
    p_diag.add_argument("--output", help="zapisz raport JSON do pliku")
    p_diag.add_argument("--print", action="store_true", help="wypisz raport JSON na stdout")
    p_diag.set_defaults(func=run_vm_diagnose)


__all__ = ["add_vm_parser", "run_vm_diagnose", "run_vm_snapshot", "run_vm_ssh", "run_vm_view"]
