#!/usr/bin/env bash
# Buduje WSZYSTKIE golden images Packerem — ŚCIŚLE SEKWENCYJNIE (jeden VM naraz;
# twarda reguła OOM tej stacji, patrz packer/README.md). Każdy build sam sprawdza
# marker `screenwright cloud-init done`; jeśli któryś wyjdzie INCOMPLETE, przerywamy.
#
# Uruchamiać w izolowanym scope, żeby OOM nie ubił sesji:
#   systemd-run --user --unit=sw-buildall --collect packer/build-all.sh
# i pollować packer/build/build-all-status.txt.
#
# NIE promuje do golden — to robi packer/promote.sh po smoke-teście.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
S="$REPO/packer/build/build-all-status.txt"
echo "BUILD-ALL START $(date +%T)" > "$S"

run() {  # name script args...
  local name="$1"; shift
  echo "--- $name: START $(date +%T) ---" >> "$S"
  if "$@"; then
    echo "--- $name: OK $(date +%T) ---" >> "$S"
  else
    rc=$?
    echo "--- $name: FAILED rc=$rc $(date +%T) — PRZERYWAM (nie startuję kolejnych VM) ---" >> "$S"
    echo "BUILD-ALL ABORTED $(date +%T)" >> "$S"
    exit "$rc"
  fi
}

run "ubuntu"     packer/build-ubuntu.sh
run "fedora-ws"  packer/build-fedora.sh ws
run "fedora-kde" packer/build-fedora.sh kde

echo "BUILD-ALL DONE $(date +%T)" >> "$S"
