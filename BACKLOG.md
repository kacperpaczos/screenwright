# Backlog

Rzeczy świadomie odłożone — z powodem, żeby nie wracać do zera przy podejmowaniu.

## Terraform dla cyklu życia maszyn (odłożone 2026-08-22)

**Stan:** zostajemy na Ansible + `virt-install` (`ansible/playbooks/`). Terraform
wraca dopiero, gdy pojawi się skala uzasadniająca deklaratywny stan (wiele
hostów / chmura / dziesiątki maszyn) albo host dostanie działający NAT na
`qemu:///system`.

**Dlaczego odłożone — diagnoza (żeby nie diagnozować drugi raz):**

1. Provider `dmacvicar/libvirt` (v0.9.8) na tej stacji łączy się z
   `qemu:///system` **mimo** `uri = "qemu:///session"` i
   `LIBVIRT_DEFAULT_URI=qemu:///session`. Dowód: `terraform console` pokazuje
   `var.libvirt_uri = "qemu:///session"`, `virsh -c qemu:///session` działa, a
   pula/domeny lądują w systemowym demonie (`virsh -c qemu:///system pool-list`
   je widzi). Domeny nie startują: `Cannot access storage file … (as
   uid:107, gid:107): Permission denied` — systemowy QEMU nie czyta puli w HOME.
2. Niezależnie: NAT `default` na `qemu:///system` na tym hoście nie forwarduje
   egressu z gości bez zmiany firewalld wymagającej roota (ping 8.8.8.8 = 100%
   loss). Dlatego i tak używamy passt (usermode), którego provider libvirt nie
   wspiera natywnie (trzeba by XSLT na XML domeny).

**Co dałby działający Terraform:** deklaratywny stan (`apply`/`destroy`, plan
diff, drift), inventory z outputów, czyste skalowanie na wiele hostów. Przy
2–4 maszynach na jednej stacji to dodatkowa warstwa bez realnego zysku — Ansible
robi cykl życia idempotentnie (`domstate` → pomija istniejące), `managedsave`/start.

**Drogi naprawy (gdyby kiedyś):** (a) firewalld na hoście → działający NAT na
`qemu:///system`, gdzie provider trafia poprawnie; albo (b) obejście błędu
session providera (pin wersji, `qemu+unix:///session?socket=…`, XSLT dla passt).

Konfiguracja Terraforma jest w historii gita (commit sprzed usunięcia) do
odtworzenia.

## Faza 3 — Mint, elementary (po G2)

Brak oficjalnych cloud image'ów. Mint: build Packerem z ISO (Ubiquity preseed,
kruchy, Mint 23 go zmieni). elementary: **brak nienadzorowanego instalatora**
(upstream) — instalacja ręczna raz, potem Packer z gotowego dysku.

## Pełne pobranie mediów

Dziś media dociągane na żądanie (`cli collect --source guest --hydrate-media N`).
Pełne (dziesiątki tys. obrazów) to zadanie wsadowe; Ubuntu deb zablokowane
wygasłym certyfikatem `appstream.ubuntu.com` (awaria Canonical).

## Retirement starego kodu matrycy (odłożone 2026-08-22 — CZĘŚCIOWO ZABLOKOWANE)

Plan 7 zakłada wycofanie `domains/matrix/` po przejściu weryfikacji wizualnej na
nowy tor. Weryfikacja cel 2 przeszła (`docs/override-deploy.md`), ale mapa
zależności (analiza 2026-08-22) pokazuje, że **całościowe usunięcie jest jeszcze
przedwczesne** — dwa bloki są nadal potrzebne:

**NIE usuwać (nadal używane):**
- `domains/matrix/distro_builders/` (668 LOC) + `vm/build/install-fedora.sh`,
  `seed-ubuntu.sh` — **budują golden images** (`fedora-ws.qcow2` itd.), których
  weryfikacja wizualna cel 2 nadal używa (overlay na golden). Plan 7 przewiduje
  zastąpienie **Packerem** — dopóki go nie ma, budowniczych nie ruszać.
- `domains/matrix/backend/{virsh,ssh}.py` + `guest.py` — **prymitywy automatyki
  VM** (VirshBackend, SshShell, wait_for_agent/shell/session). **Od 2026-08-22 są
  żywą zależnością `cli visualcheck`** (`cli/visualcheck_cmd.py`), który przekuł
  harness cel 2 w repo-tool (plan 7 linia 72) — więc te prymitywy zostają na
  stałe, nie są już „do wycofania".

**Bezpieczne do usunięcia TERAZ (silnik run-flow, w pełni zastąpiony Ansiblem;
tylko wewnętrzni + testowi konsumenci — analiza potwierdziła zero importów spoza
matrycy):** `runner.py` (682), `warm_cache.py` (230), `store_proxy.py` (355),
`domain_xml.py` (89), `drivers/` (~245), `cli/matrix_cmd.py` (309),
`matrix-spec.json`, `vm/build/run-matrix.sh`, `vm/reports/*.json`. Wraz z ich
testami (~3.6k LOC) i **modelami matrycowymi w kernelu współdzielonym**
(`shared/results.py`: `PhaseTiming`, `MatrixReport`, `_BOOT_PHASES` — reszta
pliku, `Score`/`VerificationResult`, zostaje bo używa jej `domains/verification`).

**Wiring do edycji przy usuwaniu (dokładne miejsca z analizy):**
`cli/__main__.py` (import :11, subparser :77-126, dispatch :171-174),
`domains/__init__.py` (:3, :5 — eager import matrycy), `shared/__init__.py`
(:8, :27, :28), `.importlinter` (:14, :20, :31, :39),
`tests/architecture/test_boundaries.py:9` (lista `DOMAINS`),
`tests/architecture/validate_models.py` (:10, :51-60, :67-68, :79),
`tests/unit/test_shared.py` (:10, :86-133).

**Pułapki:** `cli/collect_cmd.py` importuje `domains.corpus.guest` (INNY moduł niż
`domains.matrix.guest` — nie mylić); `vm/build/build-keypair.sh` jest
**współdzielony** z kolektorami (`docs/collectors.md:21`) — zostaje.

Sekwencja: (1) Packer → golden; (2) `visual-check` repo-tool na backend/guest;
(3) dopiero wtedy pełne usunięcie z distro_builders + backend + guest.
