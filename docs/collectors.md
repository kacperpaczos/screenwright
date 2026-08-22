# Kolektory: zdjęcia aplikacji z wnętrza dystrybucji

Realizacja celu 1 z `plans/7-stack-transformation.md` — zebranie screenshotów
**wszystkich** aplikacji każdej dystrybucji w jej natywnych formatach
(deb/rpm AppStream, flatpak/Flathub, snap), z wnętrza prawdziwych systemów.

## Stack

- **Ansible** (`ansible/`) stawia maszyny przez `virt-install` i robi całą pracę
  w gościu (role `store-tools`, `collect-catalog`). Terraform jest zaparkowany —
  patrz `../terraform/README.md`.
- **libvirt/QEMU `qemu:///session`** + sieć **passt** (usermode, bezrootowy egress;
  na tym hoście NAT `default` na `qemu:///system` nie forwarduje bez roota).
- **Python** (`domains/corpus`) tylko do modelu danych i indeksu — parsery
  AppStream/DEP-11/snapd współdzielone z kolektorami z publicznych endpointów.

## Jak uruchomić (obieg jednokomendowy)

```bash
# 0. jednorazowo: klucz SSH (jeśli nie ma) i narzędzia
vm/build/build-keypair.sh
pip install --user ansible-core            # + ~/.local/bin w PATH

# 1. postaw kolektory i zbierz katalogi (provision → wait SSH → collect)
cd ansible && ansible-playbook playbooks/site.yml

# 2. zaimportuj do korpusu (bez pobierania bajtów — same URL-e)
cd .. && python -m cli collect --source guest --distros fedora,ubuntu --output corpus --skip-media

# 3. (opcjonalnie) pobierz N obrazów na hosta w tym przebiegu
python -m cli collect --source guest --distros fedora,ubuntu --output corpus --max-media 500
```

Wynik: `corpus/index.json` (wpisy `CorpusEntry` z `source=guest-*`), media pod
`corpus/media/<app>/<distro>/<source>/`. Import jest idempotentny (dedupe po
`sha256` i po `(url, app, source)`).

## Maszyny są trwałe

Kolektory nie są kasowane po przebiegu — między przebiegami idą w `managedsave`:

```bash
virsh -c qemu:///session managedsave collector-fedora   # zamrożenie do pliku
virsh -c qemu:///session start collector-fedora         # wznowienie
python -m cli vm ... # (podgląd: virt-manager --connect qemu:///session)
```

Ponowny `ansible-playbook playbooks/provision.yml` pomija istniejące domeny
(idempotentny), a `collect.yml` odświeża katalogi w miejscu.

## Zmierzone (2026-08-22, Fedora 44 + Ubuntu 24.04)

| Źródło | Wpisy |
| --- | ---: |
| Fedora AppStream (rpm) | 12 631 |
| Flathub (flatpak) | 41 744 |
| Ubuntu DEP-11 (deb) | 5 072 |
| snap (snapd `/v2/find`) | 3 421 |
| **razem** | **62 868** (6 186 unikalnych aplikacji) |

Pełny `collect` (provision + zebranie): ~2–3 min przy istniejących obrazach
bazowych; egress przez passt (metalink Fedory 200 w 0.6 s).
