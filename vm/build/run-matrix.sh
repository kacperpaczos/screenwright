#!/usr/bin/env bash
# run-matrix.sh — wrapper na `python -m cli matrix --execute --backend virsh`.
#
# Użycie:
#   vm/build/run-matrix.sh matrix-spec.json                # wyjście: vm/reports/matrix-report.json
#   vm/build/run-matrix.sh matrix-spec.json --output X.json # własna ścieżka
#
# Dodatkowe kroki ponad CLI:
#   - Waliduje, że libvirtd działa (`virsh ping`).
#   - Waliduje, że każdy golden image z matrix-spec istnieje.
#   - Wypisuje plan przed wykonaniem (opcjonalnie --dry-run override).

set -euo pipefail

SPEC="${1:-matrix-spec.json}"
shift || true
EXTRA_ARGS=("$@")

if [[ ! -f "$SPEC" ]]; then
    echo "spec file not found: $SPEC" >&2
    exit 2
fi

LIBVIRT_URI="${SCREENWRIGHT_LIBVIRT_URI:-qemu:///session}"
if ! virsh -c "$LIBVIRT_URI" uri >/dev/null 2>&1; then
    echo "libvirt niedostępny pod $LIBVIRT_URI" >&2
    exit 3
fi

# Sprawdź istnienie golden images oraz seed ISO (bez seeda cloud-init nie
# zobaczy user-data i VM wstanie bez desktopu/sklepu — cicha porażka).
python3 - "$SPEC" <<'PY'
import json
import pathlib
import sys

spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
missing = []
for distro in spec.get("distros", []):
    for key in ("golden_image", "seed_iso"):
        value = distro.get(key)
        if value and not pathlib.Path(value).exists():
            missing.append(f"{distro.get('name', '?')}: {key} = {value}")
if missing:
    print("missing image artifacts:", *missing, sep="\n  ", file=sys.stderr)
    sys.exit(4)
PY

# Wyłuskaj --output z EXTRA_ARGS, żeby nie trafił do CLI dwa razy.
OUTPUT="vm/reports/matrix-report.json"
PASSTHROUGH=()
while [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; do
    arg="${EXTRA_ARGS[0]}"
    EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
    case "$arg" in
        --output)
            OUTPUT="${EXTRA_ARGS[0]:-$OUTPUT}"
            EXTRA_ARGS=("${EXTRA_ARGS[@]:1}")
            ;;
        --output=*) OUTPUT="${arg#--output=}" ;;
        *) PASSTHROUGH+=("$arg") ;;
    esac
done

# Najpierw plan (sucho) — widać kroki przed faktycznym uruchomieniem.
python3 -m cli matrix --spec "$SPEC"

# Potem execute — virsh faktycznie bootuje VM.
python3 -m cli matrix --spec "$SPEC" --execute --backend virsh \
    --output "$OUTPUT" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}