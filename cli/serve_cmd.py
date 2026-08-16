"""CLI subcommand: serve (dawniej poc/serve.sh).

Lokalny serwer HTTP do serwowania screenshotów w override'ach.
"""

from __future__ import annotations

import http.server
import os
import signal
import socketserver
from pathlib import Path
from typing import TYPE_CHECKING

from shared.logging import log_entry

if TYPE_CHECKING:
    import argparse

DEFAULT_PORT = 8899
DEFAULT_HOST = "127.0.0.1"
PIDFILE_NAME = ".serve.pid"
LOGFILE_NAME = ".serve.log"


def _pidfile() -> Path:
    return Path.cwd() / PIDFILE_NAME


def _logfile() -> Path:
    return Path.cwd() / LOGFILE_NAME


def run_serve_start(args: argparse.Namespace) -> int:
    host: str = args.host
    port: int = args.port
    directory = Path(args.directory)
    pidfile = _pidfile()
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
            log_entry(20, "cli.serve.already_running", pid=pid)
            return 0
        except (OSError, ValueError):
            pidfile.unlink(missing_ok=True)

    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)

    log_path = _logfile()
    log = log_path.open("a", encoding="utf-8")
    pid = os.fork()
    if pid > 0:
        pidfile.write_text(str(pid), encoding="utf-8")
        log_entry(20, "cli.serve.started", pid=pid, host=host, port=port)
        log.close()
        return 0
    os.setsid()
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(directory), **kwargs)  # type: ignore[arg-type]

    with socketserver.TCPServer((host, port), Handler) as httpd:
        httpd.serve_forever()
    return 0


def run_serve_stop() -> int:
    pidfile = _pidfile()
    if not pidfile.exists():
        log_entry(20, "cli.serve.not_running")
        return 0
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        log_entry(20, "cli.serve.stopped", pid=pid)
    except (OSError, ValueError) as exc:
        log_entry(20, "cli.serve.stop_failed", error=str(exc))
    pidfile.unlink(missing_ok=True)
    return 0


def run_serve_status(args: argparse.Namespace) -> int:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{args.host}:{args.port}/", timeout=3) as response:
            log_entry(20, "cli.serve.status", code=response.status)
            return 0
    except Exception as exc:
        log_entry(20, "cli.serve.down", error=str(exc))
        return 1
