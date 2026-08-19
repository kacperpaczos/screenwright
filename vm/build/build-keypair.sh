#!/usr/bin/env bash
# build-keypair.sh — generuje parę kluczy SSH dla screenwright-ubuntu.
#
# Użycie:
#   vm/build/build-keypair.sh
#
# Efekt:
#   ~/.ssh/screenwright_ubuntu (klucz prywatny, 600)
#   ~/.ssh/screenwright_ubuntu.pub (klucz publiczny)
#
# Bezpieczne do ponownego odpalenia — nie nadpisuje istniejącego klucza.
set -euo pipefail

KEY="$HOME/.ssh/screenwright_ubuntu"
PUB="$KEY.pub"

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [[ -f "$KEY" && -f "$PUB" ]]; then
    echo "OK: klucz już istnieje — $PUB"
    ssh-keygen -lf "$PUB" || true
    exit 0
fi

ssh-keygen -t ed25519 -N "" -f "$KEY" -C "screenwright-ubuntu"
chmod 600 "$KEY"
chmod 644 "$PUB"

echo "OK: wygenerowano $KEY + $PUB"
echo "Fingerprint:"
ssh-keygen -lf "$PUB"