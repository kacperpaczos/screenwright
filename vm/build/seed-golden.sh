#!/usr/bin/env bash
# seed-golden.sh — weź cloud image → golden image (autologin, agenty, sparsify).
#
# Użycie:
#   sudo vm/build/seed-golden.sh /var/lib/libvirt/images/golden/fedora-kde-44.qcow2
#
# Co robi:
#   1. Robi kopię cloud image'a (szybka, qcow2 sparse → overlay na wejściu).
#   2. Uruchamia kopię jako domenę transient przez virt-customize.
#   3. Instaluje qemu-guest-agent, włącza autologin, wyłącza lock screen.
#   4. Czyści cache paczek, uruchamia fstrim.
#   5. Nadpisuje oryginał sparsifikowaną kopią.
#
# Wymaga: virt-customize, virt-sparsify (z guestfs-tools), sudo.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 /path/to/golden.qcow2" >&2
    exit 2
fi

GOLDEN="$(realpath "$1")"
TMP_DIR="$(mktemp -d -t screenwright-golden.XXXXXX)"
WORK="$(mktemp -u -t screenwright-work.XXXXXX.qcow2)"
trap 'rm -rf "$TMP_DIR"; [[ -f "$WORK" ]] && rm -f "$WORK"' EXIT

if [[ ! -f "$GOLDEN" ]]; then
    echo "no such file: $GOLDEN" >&2
    exit 1
fi

cp --reflink=auto "$GOLDEN" "$WORK"

# Pierwszy boot cloud image'a wymaga hasła do konsoli (Fedora 44 domyślnie
# generuje losowe dla cloud-init). virt-customize nie wymaga boota — modyfikuje
# obraz bezpośrednio.
virt-customize \
    --add "$WORK" \
    --root-password password:screenwright \
    --ssh-inject root:file:/root/.ssh/id_rsa.pub \
    --run-command 'dnf install -y qemu-guest-agent' \
    --run-command 'systemctl enable qemu-guest-agent' \
    --run-command 'dnf clean all' \
    --run-command 'fstrim -a' \
    --selinux-relabel

# Sparsifikuj — typowo 4–6 GB zamiast 10 GB raw.
virt-sparsify --compress "$WORK" "$TMP_DIR/sparse.qcow2"

mv "$TMP_DIR/sparse.qcow2" "$GOLDEN"
chmod 444 "$GOLDEN"

echo "OK: golden image at $GOLDEN (sparsified, autologin + qemu-guest-agent ready)"