#!/usr/bin/env bash
# diagnose-ubuntu.sh — diagnostyka snap-store w VM Ubuntu przez SSH.
#
# Użycie:
#   vm/scripts/diagnose-ubuntu.sh <vm-name> [--output vm/reports/diagnose.json]
#   vm/scripts/diagnose-ubuntu.sh <vm-name> --print   # surowy JSON na stdout
#
# Wymaga: ssh-keygen pary (~/.ssh/screenwright_ubuntu), uruchomionej VM,
# qemu-guest-agent aktywnego w VM.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <vm-name> [--output PATH] [--print]" >&2
    exit 2
fi

VM="$1"
shift

PRINT_ONLY=0
OUTPUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --print) PRINT_ONLY=1 ;;
        --output) OUTPUT="$2"; shift ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
    shift
done

# Snap, na którym sondujemy media. snap-store sam ma screenshoty, ale dla
# porównań interesują nas appki z korpusu — stąd możliwość podmiany.
PROBE_SNAP="${SCREENWRIGHT_PROBE_SNAP:-gimp}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARSER="$SCRIPT_DIR/diagnose_ubuntu.py"
SSH_HELPER="$SCRIPT_DIR/ubuntu-ssh.sh"

if [[ ! -x "$SSH_HELPER" ]]; then
    echo "brak $SSH_HELPER (chmod +x vm/scripts/ubuntu-ssh.sh)" >&2
    exit 1
fi

RAW="$(mktemp)"
trap 'rm -f "$RAW"' EXIT

{
    echo "===SECTION:snapd_version==="
    "$SSH_HELPER" "$VM" -- snap version 2>&1 || true
    echo "===END_SECTION==="

    echo "===SECTION:snap_store_info==="
    "$SSH_HELPER" "$VM" -- snap info snap-store 2>&1 || true
    echo "===END_SECTION==="

    echo "===SECTION:snap_changes==="
    "$SSH_HELPER" "$VM" -- snap changes 2>&1 || true
    echo "===END_SECTION==="

    # snap-store jest confined: jego cache leży pod ~/snap/snap-store/<rev>/,
    # a NIE w ~/.cache/snap-store. Sprawdzanie tylko drugiej ścieżki dawało
    # strukturalnie zawsze 0 plików, niezależnie od stanu sklepu.
    echo "===SECTION:snap_store_cache==="
    "$SSH_HELPER" "$VM" -- 'find ~/snap/snap-store ~/.cache/snap-store -type f 2>/dev/null' || true
    echo "===END_SECTION==="

    echo "===SECTION:snapd_journal==="
    "$SSH_HELPER" "$VM" -- 'journalctl -u snapd --since "-10 min" --no-pager -n 100 2>&1 || true' || true
    echo "===END_SECTION==="

    echo "===SECTION:api_probe==="
    "$SSH_HELPER" "$VM" -- 'ss -tnp 2>/dev/null | grep -i snapcraft || true' || true
    echo "===END_SECTION==="

    # ?fields=media zwraca sam blok media. Bez tego odpowiedź to niemal cała
    # channel-map z linkami do plików .snap, a screenshoty wypadały za limit
    # `head -c` — stąd wcześniejsze raporty pełne URL-i do .snap zamiast mediów.
    echo "===SECTION:media_probe==="
    "$SSH_HELPER" "$VM" -- \
        "curl -sS -H 'Snap-Device-Series: 16' \
        'https://api.snapcraft.io/v2/snaps/info/$PROBE_SNAP?fields=media' 2>&1 \
        | head -c 8192 || true" || true
    echo "===END_SECTION==="

    # Czy gość realnie dosięga CDN-u z mediami. To INNY host niż API
    # (dashboard.snapcraft.io), więc działające API nic o nim nie mówi.
    echo "===SECTION:media_fetch==="
    "$SSH_HELPER" "$VM" -- \
        "URL=\$(curl -sS -H 'Snap-Device-Series: 16' \
            'https://api.snapcraft.io/v2/snaps/info/$PROBE_SNAP?fields=media' 2>/dev/null \
            | tr ',' '\\n' | grep -o 'https://[^\"]*site_media[^\"]*' | head -1); \
        echo \"URL=\$URL\"; \
        [ -n \"\$URL\" ] && curl -s -o /dev/null \
            -w 'http_code=%{http_code} bytes=%{size_download} time=%{time_total}\\n' \"\$URL\"" || true
    echo "===END_SECTION==="
} > "$RAW"

JSON="$(python3 "$PARSER" "$RAW")"

if [[ "$PRINT_ONLY" -eq 1 || -z "$OUTPUT" ]]; then
    echo "$JSON"
else
    mkdir -p "$(dirname "$OUTPUT")"
    echo "$JSON" > "$OUTPUT"
    echo "OK: raport w $OUTPUT"
fi