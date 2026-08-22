#!/usr/bin/env bash
# Enumeruje Snap Store przez snapd: /v2/find per kategoria (odpowiedź zawiera media[]).
set -euo pipefail
out="${1:-/tmp/snap-find}"
mkdir -p "$out"
api() { curl -sS --unix-socket /run/snapd.socket "http://localhost$1"; }
cats=$(api /v2/categories | python3 -c 'import json,sys; print("\n".join(c["name"] for c in json.load(sys.stdin)["result"]))')
for c in $cats; do
  api "/v2/find?category=$c&scope=wide" > "$out/find-$c.json"
done
# Widok "featured" i wyszukiwanie po pustym zapytaniu — snapd zwraca top snapy.
api "/v2/find?section=featured&scope=wide" > "$out/find-featured.json" || true
ls "$out" | wc -l
