#!/usr/bin/env bash
# Buduje golden Ubuntu 24.04 Packerem (packer/ubuntu.pkr.hcl).
#
# WAŻNE (lekcja z 2026-08-22): Packer kończy się „sukcesem", gdy VM się ZGASI —
# a cloud-init potrafi zgasić maszynę PO PORAŻCE instalacji (np. gdy brak kanału
# qemu-guest-agent psuje postinst i przerywa resztę). Dlatego samo `PACKER_RC=0`
# NIE wystarcza: sprawdzamy w logu konsoli marker `screenwright cloud-init done`,
# który UbuntuBuilder emituje jako OSTATNI krok. Bez niego obraz jest niekompletny
# (nie ma SSH/usera) i NIE promujemy go do golden.
#
# Obraz ląduje w packer/build/ubuntu-out/ — promocja do golden jest ręczna,
# PO smoke-teście (jeden VM naraz, patrz BACKLOG / project-host-memory-oomd).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1
SEED="$REPO/packer/build/ubuntu-seed"
OUT="$REPO/packer/build/ubuntu-out"
CLOUD="${SCREENWRIGHT_UBUNTU_CLOUD_IMG:-$HOME/.local/share/screenwright/images/golden/.cache-noble-server-cloudimg-amd64.img}"
STATUS="$REPO/packer/build/ubuntu-build-status.txt"
CONSOLE="$OUT/console.log"
DONE_MARKER="screenwright cloud-init done"

echo "START $(date +%T)" > "$STATUS"

if [ ! -f "$CLOUD" ]; then
    echo "CLOUD_IMAGE_MISSING: $CLOUD" >> "$STATUS"
    echo "DONE $(date +%T)" >> "$STATUS"
    exit 2
fi

# świeży NoCloud seed (user-data + meta-data) z klucza wywołującego
SCREENWRIGHT_SSH_PUBKEY_PATH="${SCREENWRIGHT_SSH_PUBKEY_PATH:-$HOME/.ssh/screenwright_ubuntu.pub}" \
    PYTHONPATH="$REPO" python3 -c \
    "from pathlib import Path; from domains.matrix.distro_builders.ubuntu import UbuntuBuilder; UbuntuBuilder().render_installer(Path('$SEED'))"

rm -rf "$OUT"
PACKER_LOG=1 PACKER_LOG_PATH="$REPO/packer/build/ubuntu-packer.log" \
    packer build -var "cloud_image=$CLOUD" -var "seed_dir=$SEED" -var "output_dir=$OUT" packer/ \
    > "$REPO/packer/build/ubuntu-build.log" 2>&1
rc=$?
echo "PACKER_RC=$rc $(date +%T)" >> "$STATUS"

if [ ! -f "$OUT/ubuntu-24.04.qcow2" ]; then
    echo "IMAGE_MISSING" >> "$STATUS"
    echo "DONE $(date +%T)" >> "$STATUS"
    exit 3
fi
echo "IMAGE_SIZE=$(du -h "$OUT/ubuntu-24.04.qcow2" | cut -f1)" >> "$STATUS"

sync; sleep 3
# Twardy warunek kompletności: marker cloud-init w logu konsoli.
if tr -d '\000' < "$CONSOLE" 2>/dev/null | grep -q "$DONE_MARKER"; then
    echo "CLOUD_INIT_DONE=yes" >> "$STATUS"
    # marker = cloud-init doszedł do końca, ale pojedynczy pakiet mógł się nie
    # zainstalować (nie-krytyczny) — sygnalizujemy, smoke-test jest arbitrem.
    if tr -d '\000' < "$CONSOLE" 2>/dev/null | grep -q "package_update_upgrade_install.*fail"; then
        echo "WARN=cloud-init zgłosił porażkę instalacji pakietu (nie-krytyczne, jeśli smoke OK)" >> "$STATUS"
    fi
    echo "RESULT=OK (obraz kompletny; zweryfikuj smoke-testem przed promocją do golden)" >> "$STATUS"
    status_rc=0
else
    echo "CLOUD_INIT_DONE=no" >> "$STATUS"
    echo "RESULT=INCOMPLETE — cloud-init nie zgłosił zakończenia; obraz niekompletny, NIE promować" >> "$STATUS"
    # podpowiedź diagnostyczna
    tr -d '\000' < "$CONSOLE" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' \
        | grep -iE "fail|error|cannot|unable" | tail -5 >> "$STATUS" || true
    status_rc=5
fi
echo "DONE $(date +%T)" >> "$STATUS"
exit $status_rc
