"""CLI subcommand: capture (dawniej poc/shoot.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domains.capture.models import CaptureSpec
from domains.capture.run import run as capture_run
from shared.logging import log_entry

if TYPE_CHECKING:
    import argparse


def run_capture(args: argparse.Namespace) -> int:
    spec = CaptureSpec(
        cmd=args.cmd.split(),
        out=args.out,
        timeout=args.timeout,
        settle_timeout=args.settle_timeout,
        min_wait=args.min_wait,
        stable_frames=args.stable_frames,
        require_change=args.require_change,
    )
    try:
        result = capture_run(spec)
    except Exception as exc:
        log_entry(40, "cli.capture.error", error=str(exc))
        return 2
    log_entry(
        20,
        "cli.capture.done",
        settled=result.settled,
        frames=result.frames_captured,
        elapsed=result.elapsed,
    )
    return 0
