#!/usr/bin/env bash
# refresh-screenshot-db.sh — jednokomendowe odświeżenie korpusu zrzutów, end-to-end.
#
# Happy path (clone → jeden skrypt → zaktualizowana baza):
#   1. provisioning kolektorów + zebranie katalogów z WNĘTRZA dystrybucji (Ansible),
#   2. import katalogów do indeksu korpusu (same URL-e),
#   3. pobranie bajtów zrzutów na hosta (hydrate).
#
# Zmienne (opcjonalne):
#   DISTROS=fedora,ubuntu     które dystrybucje zbierać
#   HYDRATE=20000             ile zrzutów źródłowych dociągnąć (0 = pomiń pobieranie)
#   SKIP_PROVISION=1          użyj istniejących kolektorów (pomiń Ansible)
#   OUTPUT=corpus             katalog korpusu
#
# Prereq: vm/build/build-keypair.sh (klucz), ansible-core, qemu:///session + passt.
# UWAGA host: kolektory to lekkie VM-y bez pulpitu; nie odpalać równolegle z
# buildem golden ani smoke (reguła jeden-ciężki-VM-naraz, packer/README.md).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

DISTROS="${DISTROS:-fedora,ubuntu}"
HYDRATE="${HYDRATE:-20000}"
OUTPUT="${OUTPUT:-corpus}"
KEY="${SCREENWRIGHT_SSH_PUBKEY_PATH:-$HOME/.ssh/screenwright_ubuntu.pub}"

echo "== prereqi =="
command -v ansible-playbook >/dev/null || { echo "brak ansible-core (pip install --user ansible-core)"; exit 2; }
python -m cli --help >/dev/null 2>&1 || { echo "brak działającego 'python -m cli' (pip install -e .)"; exit 2; }
[ -f "$KEY" ] || { echo "brak klucza $KEY — uruchom vm/build/build-keypair.sh"; vm/build/build-keypair.sh; }

if [ "${SKIP_PROVISION:-0}" != "1" ]; then
  echo "== 1/3 provisioning kolektorów + zbieranie katalogów (Ansible site.yml) =="
  ( cd ansible && ansible-playbook playbooks/site.yml )
else
  echo "== 1/3 pominięto provisioning (SKIP_PROVISION=1) =="
fi

echo "== 2/3 import katalogów do korpusu (same URL-e) =="
python -m cli collect --source guest --distros "$DISTROS" --output "$OUTPUT" --skip-media

if [ "$HYDRATE" != "0" ]; then
  echo "== 3/3 pobranie bajtów zrzutów na hosta (hydrate $HYDRATE) =="
  python -m cli collect --source guest --distros "$DISTROS" --hydrate-media "$HYDRATE" --output "$OUTPUT"
else
  echo "== 3/3 pominięto pobieranie (HYDRATE=0) =="
fi

echo "== gotowe =="
python3 -c "import json,sys; d=json.load(open('$OUTPUT/index.json')); e=d['entries'] if isinstance(d,dict) and 'entries' in d else d; print(f'korpus: {len(e)} wpisów')" 2>/dev/null || true
echo "media: $(find "$OUTPUT/media" -type f 2>/dev/null | wc -l) plików"
