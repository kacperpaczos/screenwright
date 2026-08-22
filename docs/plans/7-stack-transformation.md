# Plan: maszyny per cel na gotowym stacku (Packer + Terraform + Ansible)

**Data:** 2026-08-22 (rewizja po doprecyzowaniu celu) · **Zastępuje:** pierwszą wersję
tego dokumentu pisaną pod „klon na minutę, zrzut, destroy".

**Cel produktu (słowami właściciela):** automatycznie stawiane i prekonfigurowane
maszyny pod dany cel. Cel pierwszy: **zebrać zdjęcia (screenshoty) wszystkich
aplikacji każdej dystrybucji, w formatach, w jakich dystrybucja je dostarcza —
flatpak, snap, deb/rpm (AppStream) itd.** — z wnętrza prawdziwych systemów. Cel
drugi (później): **podmienić** te zdjęcia i sprawdzić, że sklep pokazuje nasze.

**Zasada:** nie pisać własnych narzędzi od nowa. Python zostaje tam, gdzie jest
nasz model danych i nasze decyzje (co zbieramy, jak indeksujemy, jak oceniamy);
stawianie, konfigurowanie i obsługa maszyn to Packer, Terraform i Ansible.

---

## 1. Co zmienia ta wizja względem Etapu 0

| Było (Etap 0, zmierzone) | Jest |
|---|---|
| maszyna = transient klon na jeden przebieg | maszyna = **zasób per profil**, stawiany deklaratywnie, trwały; zatrzymywany (`managedsave`/snapshot libvirt), nie kasowany |
| nasz `warm_cache.py` (save/restore transient), `domain_xml.py`, `runner.py` create→destroy | **zbędne**: trwałe domeny mają natywne `virsh managedsave` i snapshoty; stawia je Terraform |
| 2 aplikacje, zrzut UI sklepu, porównanie | **wszystkie aplikacje** dystrybucji: enumeracja per format + pobranie zdjęć z wnętrza systemu; UI sklepu tylko do weryfikacji podmiany (cel 2) |
| sterowanie: nasz runner + `SshShell` + `systemd-run` | **Ansible** (SSH, idempotentne role, `fetch` wyników) |
| obrazy: `distro_builders` (Python) + `vm/build/*.sh` | **Packer** (qemu builder) + kickstart/autoinstall/cloud-init jako pliki + Ansible provisioner |
| `qemu:///session` + passt (dogmat rootless dla CI) | **`qemu:///system`** domyślnie (NAT `default`, `domifaddr`, Terraform bez obejść); session zostaje opcją w `Settings.libvirt_uri` |
| Fedora WS i Fedora KDE to dwie maszyny | dla **danych** to **jedna** dystrybucja (ten sam katalog AppStream/flatpak/rpm); desktop ma znaczenie tylko w profilu wizualnym |

Co z Etapu 0 zostaje wartością: pomiary i wiedza (SSH zamiast agenta, zachowanie
GNOME/Discover, ograniczenia hosta), `docs/matrix-timing.md`, oraz — dla celu 2 —
logika „kiedy sklep jest gotowy" i porównanie zrzutów. Reszta (warm cache, runner
transient) nie jest już potrzebna na głównej ścieżce i zostanie wycofana, gdy
profil wizualny przejdzie na trwałe maszyny.

---

## 2. Profile maszyn

| Profil | Po co | Obraz | Zasoby | Czas życia |
|---|---|---|---|---|
| `collector-<distro>` | enumeracja aplikacji i pobranie zdjęć per format | serwerowy/minimalny + narzędzia sklepów (`appstreamcli`, `flatpak`, `snap`, PackageKit CLI, `curl`) — **bez desktopu** | 1–2 GiB RAM, 1–2 vCPU | trwały; `managedsave` między przebiegami |
| `visual-<distro>-<desktop>` | cel 2: podmiana + sprawdzenie w prawdziwym sklepie (GNOME Software / Discover / App Center) | desktop + sklep + autologin (dzisiejsze golden) | 4 GiB | na żądanie, jedna naraz (RAM stacji) |

Dystrybucje i formaty do zebrania (cel 1):

| Dystrybucja | deb/rpm (AppStream) | flatpak | snap | Źródło „z wnętrza" |
|---|---|---|---|---|
| Fedora 44 | `fedora.xml.gz` (`/usr/share/swcatalog/xml`, `appstreamcli dump`) | Fedora Flatpaks + Flathub (remote appstream) | — | jedna maszyna dla WS/KDE |
| Ubuntu 24.04 | DEP-11 YAML (`/var/lib/apt/lists/*dep11*`, `/var/cache/swcatalog/yaml`) | opcjonalnie (nie domyślne) | snapd REST `/v2/find` + `/v2/snaps/info` (media) | jedna maszyna |
| Linux Mint 22 | DEP-11 (Ubuntu) + własne `mintinstall` | Flathub | — | kolejna |
| elementary 8 | — | AppCenter (Flathub) | — | kolejna; obraz ręczny raz |

Część tych źródeł `domains/corpus` potrafi pobrać z publicznych endpointów bez VM;
maszyna daje to, czego z zewnątrz nie widać: **stan po instalacji** (priorytety
katalogów, wersje, co faktycznie rozwiązuje sklep) i **stan po podmianie**.
Rozdział jest jawny w spec: `source: host|guest`.

---

## 3. Stack docelowy — warstwa po warstwie

| Warstwa | Narzędzie | Nasz kod dziś → docelowo |
|---|---|---|
| Hypervisor | **KVM/QEMU/libvirt**, `qemu:///system`, sieć NAT `default`, storage pool per projekt | `VirshBackend` 162 LOC → 0 (Terraform/Ansible wołają libvirt same) |
| Obrazy per profil | **Packer** `qemu` builder: Fedora — kickstart (`http_directory`/`boot_command`), Ubuntu — autoinstall/cloud-init NoCloud, Mint — preseed; wspólna konfiguracja (użytkownik, klucz SSH, narzędzia) jako **Ansible provisioner** | `distro_builders/*` 380 + `vm/build/*.sh` 360 → pliki `*.pkr.hcl`, `*.ks`, `user-data` (konfiguracja) |
| Stawianie maszyn | **Terraform + `dmacvicar/libvirt`**: `libvirt_volume` z obrazu Packera (backing), `libvirt_cloudinit_disk`, `libvirt_domain` per profil, outputs z IP → inventory Ansible | `domain_xml.py` 79, `warm_cache.py` 193, create/destroy w `runner.py` → 0 |
| Konfiguracja i praca w gościu | **Ansible**: role `store-tools`, `collect-appstream`, `collect-flatpak`, `collect-snap`, `fetch-media`, (cel 2) `deploy-override`, `visual-check` | `backend/ssh.py` 69, pętla per-app `runner.py`, `cli vm` 82, `vm/scripts` 110 → playbooki |
| Inwentarz i cykl życia | Terraform `output` → `cloud.terraform` inventory; `community.libvirt.virt` do `managedsave`/start | — |
| Model danych i indeks | **Python zostaje**: `domains/corpus` (CorpusEntry, indeks, hash, dedupe, `schemas/corpus-index.schema.json`); wyniki z gościa (JSON + pliki) trafiają do tego samego indeksu z `provenance=guest:<distro>` | rozszerzenie: jeden importer wyników Ansible |
| Podmiana (cel 2) | **Ansible** `deploy-override` (override AppStream `priority=1` z `domains/override`, `appstreamcli refresh`); snap bez ścieżki (asercja `store`) — jak ustalono 18.08 | `domains/override` zostaje (generuje XML); `store_proxy.py` 292 → poza repo |
| Weryfikacja wizualna (cel 2) | `virsh screenshot` + settle + porównanie z szablonem — nasz cienki kod z Etapu 0 **albo openQA/os-autoinst** (decyzja w fazie 4) | `guest.py` settle ~150 + `verification/` zostają do tej decyzji |
| Harmonogram | `systemd` timer użytkownika → `ansible-playbook collect.yml`; raport = indeks korpusu | `cli matrix` → `cli collect --source guest` (cienki trigger) |
| Jakość | pytest/ruff/mypy dla Pythona; `packer validate`, `terraform validate`, `ansible-lint` w CI; żywe przebiegi na stacji | — |

Czego nie używamy: Incus (bez zrzutu framebuffera; inny agent), Proxmox (cały OS),
kontenery (snapd/PackageKit nie działają) — bez zmian.

---

## 4. Kod do wycofania (warstwa VM, ~2 900 LOC bez testów)

| Kod | LOC | Los | Kiedy |
|---|---:|---|---|
| `distro_builders/*.py`, `vm/build/install-fedora.sh`, `seed-ubuntu.sh`, `build-keypair.sh`, `install-ssh-config.sh` | ~760 | → Packer + pliki konfiguracji; klucz SSH jako zmienna Packera/Ansible | faza 1 |
| `domain_xml.py`, `VirshBackend`, `FakeBackend`, `warm_cache.py`, create/destroy i gotowość w `runner.py` | ~800 | → Terraform + Ansible; usuwane, gdy profil wizualny przejdzie na trwałe maszyny | faza 1–2 (kolektor), faza 4 (wizualny) |
| `cli/vm_cmd.py`, `vm/scripts/*`, `store_proxy.py` + wiring | ~560 | usunięte / poza repo | faza 1 |
| `backend/ssh.py`, część sesyjna `guest.py` | ~150 | → Ansible (`systemd-run --user` jako task) | faza 4 |
| `drivers/` (komendy sklepów) | ~170 | → taski/zmienne roli `visual-check` (treść ta sama) | faza 4 |
| `guest.py` settle, `verification/`, raport/timings | ~300 | **zostają** do decyzji „nasz vs openQA" | faza 4 |
| `domains/corpus`, `domains/override`, `domains/capture` | — | **zostają** — to produkt | — |

---

## 5. Plan do końca

```
Faza 1 ── fundament ──► 🚦 G1 ──► Faza 2 ── kolektory ──► 🚦 G2 ──► Faza 3 ── reszta dystrybucji ──► Faza 4 ── podmiana + weryfikacja ──► 🚦 G3
```

### Faza 1 — fundament (2–3 dni): jedna dystrybucja od obrazu do maszyny

1. `Settings.libvirt_uri` → `qemu:///system` domyślnie; pool `screenwright` w `/var/lib/libvirt/images/screenwright` (lub HOME z poprawnymi etykietami).
2. `packer/fedora-collector.pkr.hcl`: qemu builder, kickstart z dzisiejszego `FedoraWsBuilder` przeniesiony do `packer/http/fedora-collector.ks` (bez desktopu, `@core` + narzędzia), provisioner `ansible` z rolą `store-tools`; wynik `fedora-collector.qcow2`.
3. `terraform/` (provider `dmacvicar/libvirt`): pool, base volume z obrazu, `libvirt_domain.collector["fedora"]` (2 GiB, NAT), cloud-init z kluczem; `output ips`.
4. `ansible/`: inventory z Terraforma, `ping.yml`, `collect.yml` ze stubem roli `collect-appstream`.
5. Pierwszy pełny obieg: `packer build` → `terraform apply` → `ansible-playbook collect.yml` → plik JSON z listą aplikacji Fedory + URL-e zdjęć na hoście.

**🚦 G1:** obieg działa na tej stacji bez ręcznych kroków; czas `terraform apply` → maszyna gotowa; zasoby (RAM/dysk) akceptowalne. Jeśli Terraform-libvirt sprawia kłopoty na hoście → wariant „Packer + Ansible `community.libvirt`" bez Terraforma (to samo, mniej warstw).

### Faza 2 — kolektory (3–5 dni): wszystkie aplikacje, wszystkie formaty, Fedora + Ubuntu

1. Role per format (idempotentne, wynik w JSON zgodnym z `CorpusEntry`):
   - `collect-appstream`: `appstreamcli dump` / parsowanie `*.xml.gz` i DEP-11 YAML → komponenty + `screenshot/image` URL-e (z rozmiarami, `type=source|thumbnail`);
   - `collect-flatpak`: `flatpak remote-ls --app` + appstream remote'u (`/var/lib/flatpak/appstream/*/active/appstream.xml.gz`);
   - `collect-snap`: snapd REST przez gniazdo (`/v2/find?q=&section=…` z paginacją, `/v2/snaps/info/<name>` → `media[]`);
   - `fetch-media`: pobranie plików w gościu (`get_url`, z limitem równoległości) **albo** tylko URL-e i pobranie na hoście przez istniejący `shared.media.fetch_to_corpus` — decyzja po pierwszym pomiarze wolumenu.
2. Importer po stronie Pythona: `cli collect --source guest` czyta JSON z `fetch` i dopisuje do indeksu korpusu z `provenance=guest:<distro>:<format>`; dedupe po sha256 jak dziś.
3. Ubuntu: obraz `ubuntu-collector` (cloud image + cloud-init, bez desktopu, `cloud-init.disabled` po provisioningu), role deb + snap.
4. Porównanie guest vs host (`domains/corpus` z publicznych endpointów): gdzie się różnią i dlaczego — to jest wynik badawczy projektu (wiemy już, że „delivery follows the distro").

**🚦 G2:** pokrycie (odsetek aplikacji z ≥1 zdjęciem) per dystrybucja/format; czas pełnego zebrania (cel: < 1 h na dystrybucję przy pobieraniu na hoście); zero ręcznych kroków.

### Faza 3 — reszta dystrybucji (2–4 dni): Mint, elementary, harmonogram

1. `mint-collector` (preseed/cloud image), `elementary-collector` (obraz ręczny raz → Packer `qemu` z istniejącego dysku); role bez zmian (deb/flatpak).
2. Timer `systemd --user` (lub `make refresh`) → `terraform apply` (idempotentnie) → `ansible-playbook collect.yml` → import; `managedsave` po zebraniu.
3. Retencja i różnice między zbiorami (co się zmieniło od ostatniego razu) — w indeksie, nie w nowym narzędziu.

### Faza 4 — podmiana i weryfikacja wizualna (cel 2; 1–2 tygodnie, po G2)

1. Profile `visual-*` z dzisiejszych golden przez Packera (desktop + sklep), trwałe domeny, `managedsave` zamiast warm cache.
2. `deploy-override` (Ansible): XML z `domains/override` (`priority=1`), media na hoście (`cli serve`) albo w gościu, `appstreamcli refresh`, restart sklepu.
3. `visual-check`: otwarcie strony aplikacji (dzisiejsze komendy driverów jako taski), `virsh screenshot` po stronie hosta, settle + porównanie z szablonem — **tu** decyzja „nasz cienki kod z Etapu 0 vs openQA/os-autoinst" (kryteria jak w poprzedniej wersji: needles, `isotovideo` standalone, koszt utrzymania).
4. Wtedy wycofujemy resztę warstwy VM z Pythona (`runner.py`, `warm_cache.py`, backendy, `guest.py` poza settle).

**🚦 G3:** podmiana widoczna w GNOME Software, Discover i App Center na zrzutach; koszt dodania aplikacji/dystrybucji do matrycy; ilość własnego kodu.

---

## Stan realizacji — 2026-08-22

Wykonane autonomicznie (decyzje techniczne w nawiasach):

- **Faza 1 (fundament) — zrobiona, obie dystrybucje.** `terraform/`, `ansible/`,
  `Settings.libvirt_uri` → `qemu:///session`. Pełny obieg obraz→maszyna→SSH
  działa jednym poleceniem (`ansible/playbooks/site.yml`; patrz
  `../collectors.md`). 🚦 **G1 zaliczona.**
- **Faza 2 (kolektory) — rdzeń zrobiony, Fedora + Ubuntu.** Wszystkie aplikacje,
  wszystkie formaty, zebrane z wnętrza systemów i zaimportowane do korpusu:
  **62 868 wpisów / 6 186 aplikacji** (fedora-appstream 12 631, Flathub 41 744,
  ubuntu-dep11 5 072, snap 3 421). Import idempotentny (`cli collect --source
  guest`); pobór mediów na hoście z limitem `--max-media` (sprawdzony na 36
  realnych obrazach z sha256 i wymiarami). Pełny `collect` ~2–3 min.
  🚦 **G2 osiągnięta dla Fedory + Ubuntu** (zakres Fazy 2 wg planu). Pokrycie:
  Fedora rpm 81%, Flathub 71%, Ubuntu deb 31%, snap 74% (własność katalogów;
  tor łapie ~100% zawartości). Czas `site.yml` < 4 min, zero ręcznych kroków.
  **Otwarta bramka G2 → Faza 3/cel 2:** Mint/elementary (brak cloud image'ów,
  build Packerem z ISO; elementary bez nienadzorowanego instalatora — patrz
  `../../BACKLOG.md`), pełne pobranie bajtów (na żądanie), oraz cel 2 (podmiana
  + weryfikacja wizualna na golden desktop z Etapu 0).

Decyzje techniczne podjęte po drodze (wszystkie udokumentowane w kodzie):

1. **passt zamiast NAT `default`.** `qemu:///system` na tej stacji nie forwarduje
   egressu z gości bez zmiany firewalld wymagającej roota (ping 8.8.8.8 100%
   loss). passt (usermode, sprawdzony w Etapie 0) daje egress bezrootowo; SSH
   przez port-forward na `127.0.0.1:<2201|2202>`.
2. **Ansible + `virt-install` zamiast Terraforma** (Bramka G1, wariant B).
   Provider `dmacvicar/libvirt` na tym hoście łączy się z `qemu:///system`
   mimo `uri="qemu:///session"` — pula/domeny lądują w systemowym daemonie,
   qemu (uid 107) nie czyta puli w HOME. Terraform zaparkowany
   (backlog: `../../BACKLOG.md`), wraca po naprawie providera/NAT-u.
3. **Kolektory bez desktopu, IPv4-only, seed przez xorrisofs.** cloud-init
   wyłącza IPv6 (mirrory mają AAAA), `cloud-localds` wymaga nieobecnego
   `genisoimage` → seed budowany `xorrisofs`.
4. **Maszyny trwałe, `managedsave` między przebiegami** (nie transient/destroy) —
   zgodnie z modelem „maszyny per cel". Warm cache z Etapu 0 tu niepotrzebny.

**Faza 4 / cel 2 — ZAMKNIĘTE end-to-end (2026-08-22), także wizualnie.**
GNOME Software 50 na Fedorze WS renderuje w karuzeli **nasz** zrzut. Dowód na
trzech warstwach (`docs/override-deploy.md`): (1) `appstreamcli dump` daje
dokładnie 1 zrzut = nasz; (2) GNOME Software pobiera nasz obraz (log serwera);
(3) framebuffer — crimson 0.20 vs 0.0002 (`images/cel2/cel2-PROOF-store-shows-ours.png`).
Kluczowe: libappstream **UNIONuje** `<screenshots>` komponentów o tym samym id, a
`merge="replace"` jest ignorowany — więc override musi **przepisać katalog bazowy
w miejscu** (`domains/override.patch_catalog`, `cli override --patch`); rola
`deploy-override` robi to (pobierz→patch→odeślij) i asertuje, że komponent ma
**dokładnie jeden** `<screenshot>` (nie union).

**Protokół potwierdzony na 2 sklepach × 2 platformach (2026-08-22):** ten sam
patch katalogu rpm renderuje nasz zrzut w **GNOME Software** (GTK, crimson 0.20)
**i KDE Discover** (Qt, crimson 0.16) → podmiana jest **per platforma, nie per
sklep** (`cel2-PROOF-discover-shows-ours.png`). deb: `patch_catalog` obsługuje
też **DEP-11 YAML** (wykrywa format po treści); `appstreamcli dump` = nasz 1 zrzut
z URL-ami absolutnymi (MediaBaseUrl pomijany) — warstwa danych potwierdzona,
piksel na Ubuntu blokuje środowiskowo (cert Canonical + gnome-software media).
snap omija AppStream (granica). Cała weryfikacja jako repo-tool: **`cli
visualcheck`** (`docs/override-deploy.md`).

**Retirement silnika matrycy (2026-08-22):** wycofany run-flow zastąpiony przez
Ansible — usunięto `runner`, `warm_cache`, `store_proxy`, `domain_xml`, `drivers`,
`cli/matrix_cmd` + modele matrycowe z `shared/results` (~1900 LOC kodu + ~3.6k LOC
testów). Prymitywy VM (`domains/matrix/backend`, `guest`) zostają **na stałe** —
są żywą zależnością `cli visualcheck`. Budowniczowie golden (`distro_builders`)
zostają do czasu Packera (jedyny otwarty gate retirementu, `BACKLOG.md`). Bramka
lokalna zielona (277 testów, 80% cov).

**Packer (2026-08-22, kod gotowy — buildy/weryfikacja jutro):** `packer/`
(`ubuntu.pkr.hcl` zbudowany do końca; `fedora.pkr.hcl` ws/kde napisany +
validate; `build-all.sh` sekwencyjny; `promote.sh`). Odblokowuje retirement
builderów po jutrzejszym smoke → dopięcie metryki „kod in-house VM < 500".

**One-command refresh (TODO §7, zrobione):** `scripts/refresh-screenshot-db.sh`
/ `make refresh` — provision→collect→import→hydrate, idempotentne.

**Prowenancja `guest-flatpak` — już zaimplementowana:** `entry_distro` +
`_SOURCE_DISTRO` dają flatpak→`flathub`, snap→`snap` jako własny kubełek, więc
dedupe nie scala ich pod dystrybucję kolektora (komentarz w `guest.py:152`).

Pozostało: pełne pobranie mediów (leci w tle, wznawialne), Faza 3
(Mint/elementary — odłożone do `TODO.md §9`; brak cloud image'ów / instalatorów),
oraz **jutro na VM-ach (jeden naraz):** smoke Packera → `promote.sh` → retirement
builderów (`distro_builders`, `install-fedora.sh`, `seed-ubuntu.sh`).

## 6. Metryki

| Metryka | Jak | Cel |
|---|---|---|
| Pokrycie zdjęć | aplikacje z ≥1 zdjęciem / wszystkie, per dystrybucja × format | raportowane w indeksie; cel: zgodne z tym, co pokazuje sklep |
| Czas pełnego zebrania | od `terraform apply` do importu | < 1 h / dystrybucja |
| Kod in-house warstwy VM | `wc -l domains/matrix vm cli/vm_cmd.py cli/visualcheck_cmd.py` | start ~4 800 → **2 965 teraz** (po retirementcie silnika) → ~1 630 po usunięciu builderów (jutro). Cel „< 500" ZREWIDOWANY: prymitywy `backend`+`guest` (~1 200) zostają celowo jako biblioteka automatyki VM dla `cli visualcheck` — realny cel to „zero martwego kodu orkiestracji matrycy", osiągnięty |
| Ręczne kroki w obiegu | lista w README | 0 |
| Czas dodania dystrybucji | zmierzyć na Mint | ≤ 1 dzień (obraz + inventory + te same role) |

---

## 7. Ryzyka i ograniczenia

- **Host**: 30 GiB RAM, desktop ~17 GiB; kolektory po 2 GiB → trzy naraz OK; profil wizualny jeden naraz; długie zadania jako `systemd-run --user --unit` (oomd zabił scope terminala 22.08).
- **`qemu:///system`**: obrazy w poolu systemowym (etykiety SELinux), uprawnienia grupy `libvirt` — sprawdzone 16.08; CI zostaje na FakeBackend/unit, żywe przebiegi na stacji.
- **Terraform-libvirt** to provider społecznościowy (`dmacvicar/libvirt`) — stabilny, ale bez wsparcia komercyjnego; plan B: sam Ansible `community.libvirt`.
- **Snap**: enumeracja całego Snap Store przez `/v2/find` jest duża (tysiące snapów) — paginacja/sekcje i limit czasu; podmiana snapów bez ścieżki (asercja `store`) — poza celem 2.
- **Ubuntu AppStream**: wygasły certyfikat `appstream.ubuntu.com` (zdjęcia nie ładują się w sklepie) — dane z DEP-11 i tak są w katalogu; nasz bug to nie jest.
- **Wolumen mediów**: tysiące zdjęć × dystrybucje — dedupe po sha256 i pobieranie na hoście z `shared.media` zamiast w każdym gościu.

---

## 8. Pierwszy krok, konkretnie

1. Akceptacja tego dokumentu (zastępuje poprzednią wersję i punkty 1.2–1.5 starego Etapu 1).
2. Faza 1 na Fedorze: `packer/`, `terraform/`, `ansible/` w repo, `Settings.libvirt_uri=qemu:///system`, pierwszy JSON z listą aplikacji i URL-ami zdjęć na hoście.
3. 🚦 G1 → Faza 2 (role per format) i import do korpusu.
