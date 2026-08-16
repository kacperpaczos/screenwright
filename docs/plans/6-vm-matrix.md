# Plan: automated VM matrix (TODO §6)

Boot real desktop systems — Fedora (GNOME Software), Fedora KDE (Discover),
Ubuntu, Linux Mint (mintinstall), elementary OS (AppCenter) — in virtual
machines, deploy our screenshot overrides into them, and verify that the real
store UI shows the intended image. A human must be able to open a remote
desktop into any running VM on demand.

Research basis: web research performed 2026-08-15; facts below marked
*(verified)* were confirmed against current documentation, the rest is
standard libvirt/QEMU practice to be smoke-tested during milestone 1.

Updates 2026-08-16 against a real Fedora 44 / QEMU 10.2.2 / libvirt host
(autologin, overlay, transient boot, guest agent round-trip, screenshot —
see "Verification log" at the bottom):

- **SPICE → VNC as default.** QEMU 10.2.2 on Fedora 44 dropped the `-spice`
  group entirely; `spice-server` is not packaged. `virsh create` rejects
  `<graphics type='spice'/>`. VNC is now the default in `DomainConfig` and
  the rendered XML. SPICE remains allowed by the schema (`Literal["spice",
  "vnc"]`) so older hosts can opt in via `DistroSpec.domain_overrides`.
- **managedsave → save / restore.** Libvirt refuses `virsh managedsave` on
  transient domains ("cannot do managed save for transient domain"), and
  transient is what we want so clones evaporate after `destroy`. The
  warm-state pattern is now `virsh save <vm> <file>` + `virsh restore
  <file>`. Save 0.7 s, restore 1.0 s, guest agent alive after restore.
  Bonus: the save file is explicit and can be checked into a per-golden
  cache.

## Host

Fedora 44 KDE, 8 cores, 30 GiB RAM, ~520 GB free on `/home`, `/dev/kvm`
present. **libvirt/QEMU are not installed yet** — milestone 0 is
`sudo dnf install @virtualization` plus `virt-install`, `virt-viewer`,
`guestfs-tools` (for `virt-sparsify`), and enabling `libvirtd`.

Budget: with 4 GB per desktop guest, two or three VMs can run concurrently
alongside the host desktop; the matrix therefore runs distros in batches, not
all six at once.

## Architecture: golden image → linked clones → warm state

```
images/
  golden/fedora-kde-44.qcow2      read-only, chmod 444, versioned in the name
  golden/fedora-ws-44.qcow2
  golden/ubuntu-24.04.qcow2
  golden/mint-22.qcow2
  golden/elementary-8.qcow2
  clones/<run-id>/<vm>.qcow2      qcow2 overlay, created per matrix run
```

1. **One golden image per distro.** A fully installed desktop with: a fixed
   user (`test`) with autologin, screen lock / blanking / first-run wizards
   disabled, `qemu-guest-agent` and `spice-vdagent` installed, package caches
   cleaned, `fstrim` run. Then `virt-sparsify --compress` down to an expected
   4–6 GB per image.
2. **Clones are qcow2 overlays** (`qemu-img create -f qcow2 -b golden.qcow2
   -F qcow2 clone.qcow2`) — creation is instant and near-free. Never write to
   a golden image that has overlays; all clones corrupt instantly.
3. **Clones run as transient domains** (`virsh create clone.xml`) so they
   evaporate on destroy; the only cleanup is deleting the overlay file.
4. **Boot time is cut with saved RAM state**: boot a clone once to the
   logged-in desktop, `virsh save <vm> <file>`; every later `virsh restore
   <file>` resumes the full desktop session in seconds. Save files are
   explicit, versioned per golden image — a `fedora-kde-44.qcow2.save.zst`
   beside the golden image is what every clone restores from.

save / restore notes (worked end-to-end on Fedora 44, save 0.7 s, restore
1.0 s on a 2 GB guest):

- Works for transient domains (`virsh create`), unlike `managedsave`.
- Works with plain **virtio-gpu 2D**. Does not work with VirGL 3D
  (`<gl enable='yes'>`) — the migration machinery refuses. Keep 3D off.
- Save files are invalidated by QEMU upgrades on the host: after `dnf
  upgrade`, throw away the `.save` file and re-warm. An unreadable save
  fails the run (the alternative — silently falling back to a cold boot
  — is worse than a loud error).
- Save size ≈ guest RAM (~960 MB at 2 GB guest). Set
  `save_image_format = "zstd"` in `/etc/libvirt/qemu.conf` for ~2x
  compression.
- Guest clock drifts by ~10 s after restore; `virsh domtime --sync` fails
  on a guest without an RTC (Fedora cloud images fall in this bucket), so
  for screenshot timing we tolerate the skew — store layouts don't depend
  on wall time.

## Building the golden images

| Distro | Method | Status *(verified 2026-08)* |
|---|---|---|
| Fedora WS / KDE | Kickstart on the **Everything netinstall ISO** (`virt-install --initrd-inject ks.cfg --extra-args inst.ks=file:/ks.cfg`), `%packages` → `@^workstation-product-environment` or `@^kde-desktop-environment`. The live ISO does **not** accept kickstart. | Fully unattended |
| Ubuntu 24.04+ | Subiquity **autoinstall YAML** via NoCloud seed; desktop installer has full autoinstall parity since 24.04.1. First boot is slow (snap seeding) — warm up only after it settles. | Fully unattended |
| Linux Mint 22.x | Ubiquity preseed: boot with `automatic-ubiquity url=…/preseed.cfg`; must preseed locale/keyboard or Ubiquity hangs; post-install steps via `ubiquity/success_command`. Mint 23 (expected Dec 2026) replaces Ubiquity — this path will break then. | Unattended but fragile |
| elementary OS 8 | **No unattended install exists** (upstream issue elementary/installer#503 open). Install by hand once per release; clone forever after. | Manual, once |

Sizing per guest: 2–4 vCPU, 4 GB RAM (3 GB suffices for Mint/elementary),
20–25 GB virtual disk, ~9–12 GB installed.

## Host → guest control

- **Networking**: libvirt NAT (`default` network); get the IP with
  `virsh domifaddr <vm> --source agent`; ssh/scp normally.
- **Command execution without networking**: `qemu-guest-agent` over the
  virtio channel — `virsh qemu-agent-command` with `guest-exec` /
  `guest-exec-status`. Two requests, **both sent as raw JSON** (virsh
  itself does not base64-encode the payload — earlier screenwright code
  did, and the agent rejected the request with "failed to parse JSON").
  The response carries `out-data` / `err-data` base64-encoded; decode
  locally. Output is size-capped; use scp for bulk. This is how the
  matrix runs `appstreamcli refresh`, restarts the store, etc., without
  depending on ssh being up.
  `guest-exec-status` takes **only** `pid` — it has no `wait` argument
  *(verified 2026-08-16: passing one fails with "Parameter 'wait' is
  unexpected")*. The caller must poll: a still-running command answers
  `{"return":{"exited":false}}` with no `exitcode` and no `out-data`, so
  treating a single reply as final silently yields empty stdout and a
  fake exit code 0. Poll until `exited` is true, then read `exitcode`.
- **File transfer**: scp over NAT for bulk (override XML + media); optionally
  a read-only **virtiofs** share of the media directory (needs
  `<memoryBacking><source type='memfd'/><access mode='shared'/></memoryBacking>`).
- **Screenshots of the store UI**: `virsh screenshot <vm> out.png` dumps
  the framebuffer — works with no viewer attached, reliable with
  virtio-gpu 2D, **returns PNG directly** with the virtio-gpu driver
  (no ImageMagick conversion needed; that step was a historical concern
  that has not applied since the virtio-gpu backend shipped).

## Remote desktop on demand (the human path)

Zero in-guest setup required — the display is a property of the domain:

```xml
<graphics type='vnc' autoport='yes' listen='127.0.0.1'/>
<video><model type='virtio'/></video>          <!-- 2D, no <gl> -->
```

- VNC is the default. Open a view any time with `virt-viewer -c qemu:///system
  <vm>` (or `remote-viewer $(virsh domdisplay <vm>)`); attach and detach
  freely while the matrix runs.
- **SPICE** *(verified 2026-08-16 on Fedora 44 / QEMU 10.2.2)*: the
  `-spice` group is gone from upstream QEMU; `spice-server` is not in the
  distro; `virsh create` rejects SPICE XML with "spice graphics are not
  supported with this QEMU". Do not default to it. RHEL-style hosts that
  still ship SPICE can opt back in via `DistroSpec.domain_overrides`
  (`graphics: "spice"` on the corresponding `DomainConfig`). If you do,
  re-add the `<channel type='spicevmc'>` and `spice-vdagent` in the
  golden image for clipboard + dynamic resize.

## A matrix run, end to end

For each (distro, app) pair:

1. `qemu-img create -f qcow2 -F qcow2 -b <golden> <overlay>`; `virsh create`
   transient domain (fresh MAC/UUID, XML rendered from a template with
   `<name>` matching what every later `virsh` call uses).
   `virsh create` **both defines and starts** the domain, so it is the only
   call in this step *(verified 2026-08-16)*: a preceding `virsh define`
   makes the domain persistent, and it survives `destroy` as a "shut off"
   leftover instead of evaporating; a following `virsh start` fails with
   "Domain is already active".
2. **Warm path**: `virsh restore <golden>.save.zst` — the desktop session
   resumes in ~1 s with the guest agent still alive. **Cold path** (first
   run after a QEMU upgrade, or a brand-new distro): boot to desktop,
   `virsh save <vm> <golden>.save.zst`, then continue.
3. Push override: scp the catalogue XML + media (or point it at a host-served
   URL as in the existing POC), `qemu-agent-command` `guest-exec` →
   `appstreamcli refresh --force`, restart the store process, then
   `guest-exec-status` to drain stdout.
4. Drive the store to the app page (store-specific: Discover accepts
   `appstream://<id>`; GNOME Software `gnome-software --details=<id>`;
   mintinstall and AppCenter need investigation — see plan for TODO §3).
5. `virsh screenshot <vm> <out>.png` (PNG directly with virtio-gpu);
   automated check that the deployed image is visible (template match
   against our known screenshot beats pixel-perfect comparison, since
   stores letterbox and scale).
6. On demand, a human runs `virt-viewer <vm>` and inspects interactively.
7. `virsh destroy`; delete the overlay. Result (pass/fail + store
   screenshot) lands in the comparison dataset from TODO §2.

## Milestones

- [x] **M0 — host prep** *(done 2026-08-16)*: `virt-install`, `virt-viewer`,
  `guestfs-tools`, `cloud-utils` installed; `virtqemud`/`virtnetworkd`/
  `virtstoraged`/`virtnodedevd`/`virtlogd` sockets enabled; NAT `default`
  network active + autostart; user in the `libvirt` group and
  `qemu:///system` reachable without sudo; storage laid out as
  `/var/lib/libvirt/images/{golden,clones,seed}` owned by the run user
  (standard path keeps the SELinux labels correct — `/home` does not).
  Still open: commit a `vm/` directory with the domain template XML and a
  `README`.
- [ ] **M1 — proof on one distro**: Fedora KDE golden image via kickstart;
  verify linked clone + save/restore + `virsh screenshot` +
  virt-viewer on demand; re-run the existing KCalc/Discover POC inside the
  VM. This retires the riskiest assumptions (save/restore with a desktop,
  screenshot reliability).
- [ ] **M2 — remaining unattended distros**: Fedora Workstation, Ubuntu,
  Mint golden images, each built by a script under `vm/build/`.
- [ ] **M3 — elementary**: one manual install, then scripted golden-ization
  (autologin, agents, sparsify) so only the installer clicks are manual.
- [ ] **M4 — orchestration**: `vm/run-matrix.sh` implementing the run loop
  above, batching by available RAM; results written as structured JSON per
  (distro, app).
- [ ] **M5 — docs**: “how to run the matrix” in `docs/`, including the
  re-warm procedure after host QEMU upgrades.

## Open questions

- How to drive mintinstall and AppCenter to a specific app page from the
  command line (needed for step 4; falls out of the TODO §3 store research).
  **Discover is settled** *(verified 2026-08-16 against the installed
  plasma-discover 6.7.4)*: `plasma-discover --application appstream://<id>`
  is a documented option. There is no `org.kde.discover` D-Bus service with
  an `openApp` method — the only name on the session bus is
  `org.kde.discover.notifier`, a different process — so the qdbus form in
  `domains/matrix/drivers/discover.py` cannot work.
- Whether Ubuntu's store path should test GNOME Software (deb/appstream),
  snap-store, or both — decide during M2.
- Mint 23 will need a new unattended-install recipe when it lands.

## Verification log (real host, Fedora 44 + QEMU 10.2.2 + libvirt)

Done 2026-08-16 — every claim above marked *(verified)* traces back to one
of these:

- `virt-xml-validate` accepts the rendered domain XML.
- `qemu-img create -f qcow2 -F qcow2 -b golden.qcow2 clone.qcow2` — overlay
  ~200 KiB on disk, created instantly.
- `virsh create <xml>` with VNC graphics — transient domain boots, cloud-init
  finishes, VM gets an IP via the default NAT network.
- `virsh qemu-agent-command <vm> '{"execute":"guest-ping"}'` — returns
  `{"return":{}}` (gating requirement for `guest-exec`).
- `virsh domifaddr <vm> --source agent` — returns an address; ssh-able.
- `virsh save <vm> <file>` + `virsh restore <file>` — 0.7 s save, 1.0 s
  restore, guest agent alive after restore.
- `virsh screenshot <vm> out.png` — 1280x800 PNG of the running Fedora
  console, no conversion step needed (virtio-gpu emits PNG directly).
- DOM failures (since fixed in code): base64-encoded `qemu-agent-command`
  payload, XML passed as `virsh create /dev/stdin` without `input=`, and
  a domain name in XML that did not match the `virsh start <name>` call.
  All three now have regression tests in `tests/unit/domains/test_virsh.py`
  and `tests/integration/test_matrix_runner.py`.
- Still failing against a live host as of 2026-08-16, and invisible to the
  mocked tests: `guest-exec-status` sent with `wait: true` (rejected by the
  agent), and the `define` → `create` → `start` sequence in
  `domains/matrix/runner.py` (leaves a persistent domain behind, then
  errors on `start`). Both were reproduced on a Fedora 44 cloud guest.
