#!/usr/bin/env bash
# Promuje zweryfikowany (smoke-test!) obraz Packera do golden, z backupem starego.
# Użycie:  packer/promote.sh packer/build/ubuntu-out/ubuntu-24.04.qcow2
#          (nazwa docelowa = basename źródła)
set -uo pipefail
SRC="${1:-}"
[ -n "$SRC" ] && [ -f "$SRC" ] || { echo "usage: $0 <path/to/built.qcow2>  (plik musi istnieć)" >&2; exit 2; }
GOLDEN_DIR="${SCREENWRIGHT_IMAGE_ROOT:-$HOME/.local/share/screenwright/images}/golden"
NAME="$(basename "$SRC")"
DST="$GOLDEN_DIR/$NAME"
mkdir -p "$GOLDEN_DIR"
if [ -f "$DST" ]; then
    BAK="$DST.bak-$(date +%Y%m%d-%H%M%S)"
    echo "backup istniejącego golden → $BAK"
    # golden jest 444; do przeniesienia potrzeba zapisu w katalogu, nie w pliku
    mv -f "$DST" "$BAK"
fi
cp --reflink=auto "$SRC" "$DST"
chmod 444 "$DST"
echo "OK: promowano $NAME → $DST"
echo "przypomnienie: zweryfikuj smoke-testem PRZED promocją (boot → SSH → sklep)"
