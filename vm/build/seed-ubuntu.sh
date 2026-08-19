#!/usr/bin/env bash
# seed-ubuntu.sh — Ubuntu 24.04 cloud image → golden image z PEŁNYM desktopem.
#
# Użycie:
#   vm/build/seed-ubuntu.sh [~/.local/share/screenwright/images/golden/ubuntu-24.04.qcow2]
#
# BEZ sudo: wszystko leci w qemu:///session, obrazy w HOME. Do niczego tutaj
# nie są potrzebne prawa roota — /dev/kvm jest 0666, a passt (sieć usermode)
# i libguestfs działają jako zwykły użytkownik.
#
# Co robi (jednorazowy provisioning, ~20-40 min — instaluje cały ubuntu-desktop):
#   1. Pobiera serwerowy cloud image Ubuntu 24.04 (jeśli go nie ma w cache).
#   2. Renderuje NoCloud seed (user-data + meta-data) przez UbuntuBuilder,
#      z kluczem publicznym użytkownika wywołującego.
#   3. Pakuje seed.iso (volume label 'cidata') i zapisuje go trwale.
#   4. PROVISIONING BOOT: virt-install --import z podpiętym seedem. cloud-init
#      instaluje ubuntu-desktop, gnome-software i snap-store, ustawia autologin,
#      po czym gasi maszynę (power_state: poweroff). `--wait -1` wraca właśnie
#      wtedy — zgaszenie domeny JEST sygnałem „instalacja skończona".
#   5. virt-sparsify → golden image, chmod 444.
#
# Dlaczego provisioning, a nie seed podpięty do klonów w matrycy: overlay jest
# kasowany przy teardownie, więc cloud-init instalowałby desktop od nowa przy
# KAŻDYM przebiegu. Golden ma mieć wszystko już w środku.
#
# Wymaga: virt-install, virsh, virt-sparsify (guestfs-tools), xorriso, curl, passt.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIBVIRT_URI="${SCREENWRIGHT_LIBVIRT_URI:-qemu:///session}"
IMAGE_ROOT="${SCREENWRIGHT_IMAGE_ROOT:-$HOME/.local/share/screenwright/images}"
GOLDEN="$(realpath -m "${1:-$IMAGE_ROOT/golden/ubuntu-24.04.qcow2}")"
GOLDEN_DIR="$(dirname "$GOLDEN")"
GOLDEN_BASE="$(basename "${GOLDEN%.qcow2}")"
SEED_OUT="$(dirname "$GOLDEN_DIR")/seed/${GOLDEN_BASE}-seed.iso"
DOMAIN="screenwright-build-ubuntu"
CLOUD_IMG_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
CACHE_IMG="$GOLDEN_DIR/.cache-noble-server-cloudimg-amd64.img"
VIRSH="virsh -c $LIBVIRT_URI"

PUBKEY="${SCREENWRIGHT_SSH_PUBKEY_PATH:-$HOME/.ssh/screenwright_ubuntu.pub}"

# Nieznane --osinfo wywala virt-install; bierzemy pierwsze dostępne na hoście.
pick_osinfo() {
    local candidate
    for candidate in "$@"; do
        if osinfo-query os 2>/dev/null | grep -qE "^ *$candidate +\|"; then
            echo "$candidate"
            return 0
        fi
    done
    echo "linux2022"
}

OSINFO="$(pick_osinfo ubuntu24.04 ubuntu23.10 ubuntu22.04)"

# UWAGA: nie /tmp — na Fedorze to tmpfs, więc 25-GB obraz w budowie zjadałby RAM.
BUILD_DIR="$IMAGE_ROOT/build"
mkdir -p "$BUILD_DIR"
WORK_DIR="$(mktemp -d "$BUILD_DIR/ubuntu-seed.XXXXXX")"
WORK_QCOW2="$WORK_DIR/ubuntu.qcow2"
SEED_DIR="$WORK_DIR/seed"
SEED_ISO="$WORK_DIR/seed.iso"
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

for tool in virt-install virsh virt-sparsify xorrisofs qemu-img curl; do
    command -v "$tool" >/dev/null || { echo "brak narzędzia: $tool" >&2; exit 1; }
done

if $VIRSH dominfo "$DOMAIN" >/dev/null 2>&1; then
    echo "domena $DOMAIN już istnieje — usuwam pozostałość po poprzednim buildzie"
    $VIRSH destroy "$DOMAIN" >/dev/null 2>&1 || true
    $VIRSH undefine "$DOMAIN" --nvram >/dev/null 2>&1 || true
fi

mkdir -p "$GOLDEN_DIR" "$(dirname "$SEED_OUT")"

if [[ ! -f "$CACHE_IMG" ]]; then
    echo "pobieram cloud image Ubuntu 24.04..."
    curl -fL --progress-bar -o "$CACHE_IMG.part" "$CLOUD_IMG_URL"
    mv "$CACHE_IMG.part" "$CACHE_IMG"
else
    echo "używam cache: $CACHE_IMG"
fi

cp --reflink=auto "$CACHE_IMG" "$WORK_QCOW2"

echo "renderuję NoCloud seed (klucz: $PUBKEY)..."
SCREENWRIGHT_SSH_PUBKEY_PATH="$PUBKEY" PYTHONPATH="$REPO_ROOT" \
    python3 - "$SEED_DIR" <<'PY'
import sys
from pathlib import Path

from domains.matrix.distro_builders.ubuntu import UbuntuBuilder

out_dir = Path(sys.argv[1])
UbuntuBuilder().render_installer(out_dir)
print(f"OK: seed w {out_dir}")
PY

echo "pakuję seed.iso (volume label 'cidata')..."
xorrisofs -output "$SEED_ISO" -joliet -rock -V cidata "$SEED_DIR" 2>/dev/null

# Poprzedni seed jest 444; bez roota `cp` nie otworzy go do zapisu.
rm -f "$SEED_OUT"
cp "$SEED_ISO" "$SEED_OUT"
chmod 444 "$SEED_OUT"
echo "seed zapisany: $SEED_OUT"

echo "rozszerzam dysk do 25 GB (pełny ubuntu-desktop nie zmieści się w 3.5 GB)..."
qemu-img resize "$WORK_QCOW2" 25G

echo
echo "=== PROVISIONING BOOT — to potrwa 20-40 min (instalacja desktopu) ==="
echo "    podgląd na żywo:  tail -f $CONSOLE_LOG"
echo
virt-install \
    --connect "$LIBVIRT_URI" \
    --name "$DOMAIN" \
    --memory 4096 \
    --vcpus 2 \
    --import \
    --disk "path=$WORK_QCOW2,format=qcow2,bus=virtio" \
    --disk "path=$SEED_ISO,device=cdrom,readonly=on" \
    --network user,backend.type=passt \
    --osinfo "name=$OSINFO" \
    --graphics none \
    --serial "file,path=$CONSOLE_LOG" \
    --noautoconsole \
    --wait -1

if ! grep -q "screenwright cloud-init done" "$CONSOLE_LOG" 2>/dev/null; then
    echo >&2
    echo "BŁĄD: domena zgasła, ale cloud-init nie zgłosił zakończenia." >&2
    echo "Ostatnie 40 linii konsoli:" >&2
    tail -40 "$CONSOLE_LOG" >&2 || true
    exit 5
fi
echo "cloud-init zakończony pomyślnie."

$VIRSH undefine "$DOMAIN" --nvram >/dev/null 2>&1 || true

# virt-sparsify montuje system plików gościa i potrafi paść na "Read-only
# file system". qemu-img convert nie montuje niczego — kompresuje i wyrzuca
# niezaalokowane klastry. Próbujemy lepszego, spadamy na pewniejsze.
SPARSE="$WORK_DIR/ubuntu-sparse.qcow2"
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
echo "    Zawiera: ubuntu-desktop, gnome-software, snap-store, qemu-guest-agent,"
echo "             autologin użytkownika 'test', SSH z kluczem $PUBKEY"
echo
echo "Klony w matrycy NIE potrzebują seed ISO — wszystko jest już w obrazie."
echo "Sprawdź maszynę ręcznie:  python -m cli vm ssh <domena> -- snap list"
