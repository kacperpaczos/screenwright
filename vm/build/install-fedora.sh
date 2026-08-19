#!/usr/bin/env bash
# install-fedora.sh — pełna, nienadzorowana instalacja Fedory 44 → golden image.
#
# Użycie:
#   vm/build/install-fedora.sh kde [~/.local/share/screenwright/images/golden/fedora-kde.qcow2]
#   vm/build/install-fedora.sh ws  [~/.local/share/screenwright/images/golden/fedora-ws.qcow2]
#
# BEZ sudo: qemu:///session, obrazy w HOME, sieć usermode (passt).
#
# Warianty:
#   kde → Plasma + Discover           (DistroName.FEDORA_KDE)
#   ws  → GNOME + GNOME Software      (DistroName.FEDORA_WS)
#
# Co robi (~30-60 min na wariant — Anaconda ciągnie paczki z mirrora):
#   1. Renderuje kickstart przez FedoraKdeBuilder / FedoraWsBuilder, wstrzykując
#      klucz publiczny użytkownika wywołującego (sshkey --username=test).
#   2. virt-install --location + --initrd-inject: Anaconda instaluje system.
#   3. Kickstart kończy się `poweroff`, więc `--wait -1` wraca dokładnie wtedy,
#      gdy instalacja jest skończona (przy `reboot` build by się zapętlił).
#   4. virt-sparsify → golden image, chmod 444.
#
# Wymaga: virt-install, virsh, virt-sparsify (guestfs-tools), passt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIBVIRT_URI="${SCREENWRIGHT_LIBVIRT_URI:-qemu:///session}"
IMAGE_ROOT="${SCREENWRIGHT_IMAGE_ROOT:-$HOME/.local/share/screenwright/images}"
FEDORA_RELEASE=44
MIRROR="https://download.fedoraproject.org/pub/fedora/linux/releases/${FEDORA_RELEASE}/Everything/x86_64/os/"

usage() {
    echo "usage: $0 kde|ws [/path/to/golden.qcow2]" >&2
    exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
VARIANT="$1"

case "$VARIANT" in
    kde)
        BUILDER="FedoraKdeBuilder"
        KS_NAME="fedora-kde.ks"
        DEFAULT_GOLDEN="$IMAGE_ROOT/golden/fedora-kde.qcow2"
        ;;
    ws)
        BUILDER="FedoraWsBuilder"
        KS_NAME="fedora-ws.ks"
        DEFAULT_GOLDEN="$IMAGE_ROOT/golden/fedora-ws.qcow2"
        ;;
    *) usage ;;
esac

# Baza osinfo rzadko nadąża za najnowszą Fedorą (dla 44 zwykle jej nie ma),
# a nieznane --osinfo wywala virt-install. Bierzemy najbliższe dostępne.
pick_osinfo() {
    local candidate
    for candidate in "$@"; do
        if osinfo-query os short-id 2>/dev/null | grep -qx " *$candidate *"; then
            echo "$candidate"
            return 0
        fi
        if osinfo-query os 2>/dev/null | grep -qE "^ *$candidate +\|"; then
            echo "$candidate"
            return 0
        fi
    done
    echo "linux2022"
}

OSINFO="$(pick_osinfo fedora44 fedora43 fedora42 fedora41 fedora40)"
echo "osinfo: $OSINFO"

GOLDEN="$(realpath -m "${2:-$DEFAULT_GOLDEN}")"
GOLDEN_DIR="$(dirname "$GOLDEN")"
DOMAIN="screenwright-build-fedora-$VARIANT"
VIRSH="virsh -c $LIBVIRT_URI"

PUBKEY="${SCREENWRIGHT_SSH_PUBKEY_PATH:-$HOME/.ssh/screenwright_ubuntu.pub}"

# UWAGA: nie /tmp — na Fedorze to tmpfs, więc obraz w budowie zjadałby RAM.
BUILD_DIR="$IMAGE_ROOT/build"
mkdir -p "$BUILD_DIR"
WORK_DIR="$(mktemp -d "$BUILD_DIR/fedora-$VARIANT.XXXXXX")"
WORK_QCOW2="$WORK_DIR/fedora.qcow2"
KS_DIR="$WORK_DIR/ks"
CONSOLE_LOG="$WORK_DIR/console.log"

# Katalog roboczy kasujemy TYLKO po sukcesie. Wcześniejsza wersja robiła to
# zawsze i skasowała gotowy obraz po 40 minutach budowy, bo wysypał się dopiero
# krok kompresji. Produkt budowy ma przeżyć porażkę ostatniego kroku.
SUCCESS=0
cleanup() {
    if $VIRSH dominfo "$DOMAIN" >/dev/null 2>&1; then
        $VIRSH destroy "$DOMAIN" >/dev/null 2>&1 || true
        $VIRSH undefine "$DOMAIN" --nvram >/dev/null 2>&1 || true
    fi
    if [[ "$SUCCESS" -eq 1 ]]; then
        rm -rf "$WORK_DIR"
    else
        echo >&2
        echo "Katalog roboczy ZACHOWANY (budowa nieukończona):" >&2
        echo "    $WORK_DIR" >&2
        echo "Obraz w środku może być sprawny — sprawdź, zanim skasujesz." >&2
    fi
}
trap cleanup EXIT

if [[ ! -f "$PUBKEY" ]]; then
    echo "brak klucza publicznego: $PUBKEY" >&2
    echo "uruchom najpierw (bez sudo): vm/build/build-keypair.sh" >&2
    exit 1
fi

for tool in virt-install virsh virt-sparsify qemu-img; do
    command -v "$tool" >/dev/null || { echo "brak narzędzia: $tool" >&2; exit 1; }
done

if $VIRSH dominfo "$DOMAIN" >/dev/null 2>&1; then
    echo "domena $DOMAIN już istnieje — usuwam pozostałość po poprzednim buildzie"
    $VIRSH destroy "$DOMAIN" >/dev/null 2>&1 || true
    $VIRSH undefine "$DOMAIN" --nvram >/dev/null 2>&1 || true
fi

mkdir -p "$GOLDEN_DIR"

echo "renderuję kickstart ($BUILDER, klucz: $PUBKEY)..."
SCREENWRIGHT_SSH_PUBKEY_PATH="$PUBKEY" PYTHONPATH="$REPO_ROOT" \
    python3 - "$KS_DIR" "$BUILDER" <<'PY'
import sys
from pathlib import Path

import domains.matrix.distro_builders as builders

out_dir = Path(sys.argv[1])
builder = getattr(builders, sys.argv[2])()
target = builder.render_installer(out_dir)
print(f"OK: kickstart w {target}")
PY

# Wysyp się teraz, a nie po 40 minutach pobierania paczek.
PYTHONPATH="$REPO_ROOT" python3 - "$KS_DIR/$KS_NAME" <<'PY'
import sys

from pykickstart.parser import KickstartParser
from pykickstart.version import makeVersion

KickstartParser(makeVersion("F40")).readKickstart(sys.argv[1])
print("OK: kickstart waliduje się przez pykickstart")
PY

qemu-img create -f qcow2 "$WORK_QCOW2" 20G >/dev/null

echo
echo "=== INSTALACJA FEDORA $VARIANT — to potrwa 30-60 min ==="
echo "    podgląd na żywo:  tail -f $CONSOLE_LOG"
echo
virt-install \
    --connect "$LIBVIRT_URI" \
    --name "$DOMAIN" \
    --memory 4096 \
    --vcpus 2 \
    --disk "path=$WORK_QCOW2,format=qcow2,bus=virtio" \
    --network user,backend.type=passt \
    --location "$MIRROR" \
    --initrd-inject "$KS_DIR/$KS_NAME" \
    --extra-args "inst.ks=file:/$KS_NAME inst.repo=$MIRROR ip=dhcp console=ttyS0,115200" \
    --osinfo "name=$OSINFO" \
    --graphics none \
    --serial "file,path=$CONSOLE_LOG" \
    --noautoconsole \
    --wait -1 \
    --noreboot

if grep -qE "Kickstart|anaconda.*(error|traceback)" "$CONSOLE_LOG" 2>/dev/null &&
   grep -qiE "installation failed|kickstart error" "$CONSOLE_LOG" 2>/dev/null; then
    echo >&2
    echo "BŁĄD: Anaconda zgłosiła problem. Ostatnie 40 linii konsoli:" >&2
    tail -40 "$CONSOLE_LOG" >&2
    exit 5
fi

$VIRSH undefine "$DOMAIN" --nvram >/dev/null 2>&1 || true

# virt-sparsify montuje system plików gościa i potrafi paść na "Read-only
# file system". qemu-img convert nie montuje niczego — kompresuje i wyrzuca
# niezaalokowane klastry. Próbujemy lepszego, spadamy na pewniejsze.
SPARSE="$WORK_DIR/fedora-sparse.qcow2"
echo "kompresja obrazu (virt-sparsify)..."
if ! virt-sparsify --check-tmpdir=ignore --compress "$WORK_QCOW2" "$SPARSE" 2>"$WORK_DIR/sparsify.log"; then
    echo "virt-sparsify nie dał rady:"
    tail -3 "$WORK_DIR/sparsify.log" || true
    echo "spadam na qemu-img convert -c (nie montuje systemu plików gościa)..."
    rm -f "$SPARSE"
    qemu-img convert -c -O qcow2 "$WORK_QCOW2" "$SPARSE"
fi

rm -f "$GOLDEN"
mv "$SPARSE" "$GOLDEN"
chmod 444 "$GOLDEN"
SUCCESS=1

echo
echo "OK: golden image gotowy: $GOLDEN"
case "$VARIANT" in
    kde) echo "    Zawiera: Plasma + Discover, autologin 'test', SSH, qemu-guest-agent" ;;
    ws)  echo "    Zawiera: GNOME + GNOME Software, autologin 'test', SSH, qemu-guest-agent" ;;
esac
