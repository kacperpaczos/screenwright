#!/usr/bin/env bash
# ubuntu-ssh.sh — SSH z hosta do VM (klucz, automatyczny port).
#
# Użycie:
#   vm/scripts/ubuntu-ssh.sh <vm-name> [-- command args...]
#   vm/scripts/ubuntu-ssh.sh <vm-name>          # sesja interaktywna
#   vm/scripts/ubuntu-ssh.sh <vm-name> -- snap version
#
# W qemu:///session gość siedzi za usermode NAT-em (passt) i NIE ma adresu
# osiągalnego z hosta — `virsh domifaddr` zwróci coś w rodzaju 10.0.2.15,
# do czego nie da się połączyć. Wchodzimy przez przekierowanie portu, które
# domena deklaruje w swoim XML-u:
#
#   <portForward proto="tcp" address="127.0.0.1">
#     <range start="<PORT>" to="22"/>
#   </portForward>
#
# Port nadaje runner (`pick_ssh_port`), więc odczytujemy go z żywej domeny,
# zamiast zgadywać.
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <vm-name> [-- command args...]" >&2
    exit 2
fi

VM_NAME="$1"
shift

LIBVIRT_URI="${SCREENWRIGHT_LIBVIRT_URI:-qemu:///session}"
KEY="${SCREENWRIGHT_SSH_KEY:-$HOME/.ssh/screenwright_ubuntu}"

if [[ ! -f "$KEY" ]]; then
    echo "brak klucza prywatnego: $KEY (uruchom vm/build/build-keypair.sh)" >&2
    exit 1
fi

XML="$(virsh -c "$LIBVIRT_URI" dumpxml "$VM_NAME" 2>/dev/null || true)"
if [[ -z "$XML" ]]; then
    echo "nie mogę pobrać XML domeny $VM_NAME (czy działa? virsh -c $LIBVIRT_URI list)" >&2
    exit 3
fi

# <range start="PORT" to="22"/> — bierzemy start z wiersza kierującego na port 22.
PORT="$(printf '%s\n' "$XML" \
    | grep -o '<range start="[0-9]*" to="22"' \
    | grep -o 'start="[0-9]*"' \
    | grep -o '[0-9]*' \
    | head -1)"

if [[ -z "${PORT:-}" ]]; then
    echo "domena $VM_NAME nie ma przekierowania portu na 22." >&2
    echo "W trybie session SSH działa tylko przez <portForward> — sprawdź XML:" >&2
    echo "    virsh -c $LIBVIRT_URI dumpxml $VM_NAME | grep -A3 portForward" >&2
    exit 4
fi

exec ssh \
    -i "$KEY" \
    -p "$PORT" \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=30 \
    test@127.0.0.1 \
    "$@"
