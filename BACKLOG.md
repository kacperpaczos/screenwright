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
