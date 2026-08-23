#!/usr/bin/env bash
# Buduje golden Fedora (ws|kde) Packerem (packer/fedora.pkr.hcl), wariant cloud-init.
#
# NIEZWERYFIKOWANE buildem (2026-08-22) — pierwszy build jutro; instalacja grupy
# pulpitu przez dnf jest ciężka i może wymagać strojenia (nazwy grup, autologin).
# Jak Ubuntu: sprawdza marker `screenwright cloud-init done`; bez niego INCOMPLETE.
#
# Użycie:  packer/build-fedora.sh ws | kde
# Zmienne: SCREENWRIGHT_FEDORA_CLOUD_IMG (ścieżka do Fedora Cloud Base qcow2),
#          SCREENWRIGHT_FEDORA_CLOUD_URL (URL do pobrania, gdy brak cache).
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

VARIANT="${1:-}"
case "$VARIANT" in
  ws)  DESKTOP_ENV="@^workstation-product-environment"; STORE_PKG="gnome-software"
       AUTOLOGIN_CMDS='mkdir -p /etc/gdm && printf "[daemon]\nAutomaticLoginEnable=True\nAutomaticLogin=test\n" > /etc/gdm/custom.conf'
       # wygasza gnome-initial-setup (kreator pierwszego logowania zasłania sklep)
       FIRSTRUN_CMDS='rm -f /etc/xdg/autostart/gnome-initial-setup-first-login.desktop /etc/xdg/autostart/org.gnome.Software.desktop'
       VM_NAME="fedora-ws.qcow2" ;;
  kde) DESKTOP_ENV="@^kde-desktop-environment"; STORE_PKG="plasma-discover"
       AUTOLOGIN_CMDS='mkdir -p /etc/sddm.conf.d && printf "[Autologin]\nUser=test\nSession=plasma\n" > /etc/sddm.conf.d/autologin.conf'
       # wygasza kreator „Welcome to Plasma" (plasma-welcome), który zasłania Discover
       FIRSTRUN_CMDS='rm -f /etc/xdg/autostart/org.kde.plasma.welcome.desktop /etc/xdg/autostart/*plasma*welcome*.desktop /etc/xdg/autostart/*welcome*.desktop'
       VM_NAME="fedora-kde.qcow2" ;;
  *)   echo "usage: $0 ws|kde" >&2; exit 2 ;;
esac

SEED="$REPO/packer/build/fedora-$VARIANT-seed"
OUT="$REPO/packer/build/fedora-$VARIANT-out"
STATUS="$REPO/packer/build/fedora-$VARIANT-build-status.txt"
CONSOLE="$OUT/console.log"
PUBKEY_PATH="${SCREENWRIGHT_SSH_PUBKEY_PATH:-$HOME/.ssh/screenwright_ubuntu.pub}"
CLOUD="${SCREENWRIGHT_FEDORA_CLOUD_IMG:-$HOME/.local/share/screenwright/images/golden/.cache-fedora-cloud-base.qcow2}"
DONE_MARKER="screenwright cloud-init done"

echo "START $VARIANT $(date +%T)" > "$STATUS"

[ -f "$PUBKEY_PATH" ] || { echo "PUBKEY_MISSING: $PUBKEY_PATH (uruchom vm/build/build-keypair.sh)" >> "$STATUS"; exit 2; }

if [ ! -f "$CLOUD" ]; then
  URL="${SCREENWRIGHT_FEDORA_CLOUD_URL:-}"
  [ -n "$URL" ] || { echo "CLOUD_IMAGE_MISSING: $CLOUD — ustaw SCREENWRIGHT_FEDORA_CLOUD_URL by pobrać" >> "$STATUS"; exit 2; }
  echo "pobieram Fedora Cloud Base..." >> "$STATUS"
  if ! { curl -fL --progress-bar -o "$CLOUD.part" "$URL" && mv "$CLOUD.part" "$CLOUD"; }; then
    echo "DOWNLOAD_FAILED" >> "$STATUS"; exit 2
  fi
fi

# render NoCloud seed (user-data + meta-data)
mkdir -p "$SEED"
PUBKEY="$(cat "$PUBKEY_PATH")"
cat > "$SEED/meta-data" <<META
instance-id: screenwright-fedora-$VARIANT
local-hostname: screenwright
META
cat > "$SEED/user-data" <<CLOUD
#cloud-config
ssh_pwauth: false
users:
  - name: test
    groups: [wheel]
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - $PUBKEY
runcmd:
  - [ dnf, -y, install, qemu-guest-agent, openssh-server, $STORE_PKG ]
  - dnf -y install "$DESKTOP_ENV"
  - systemctl enable sshd qemu-guest-agent
  - systemctl set-default graphical.target
  - $AUTOLOGIN_CMDS
  - $FIRSTRUN_CMDS
power_state:
  mode: poweroff
  timeout: 180
  condition: true
final_message: "$DONE_MARKER after \$UPTIME seconds"
CLOUD

rm -rf "$OUT"
echo "PACKER_START $(date +%T)" >> "$STATUS"
PACKER_LOG=1 PACKER_LOG_PATH="$REPO/packer/build/fedora-$VARIANT-packer.log" \
  packer build -var "cloud_image=$CLOUD" -var "seed_dir=$SEED" -var "output_dir=$OUT" -var "vm_name=$VM_NAME" packer/fedora.pkr.hcl \
  > "$REPO/packer/build/fedora-$VARIANT-build.log" 2>&1
rc=$?
echo "PACKER_RC=$rc $(date +%T)" >> "$STATUS"

[ -f "$OUT/$VM_NAME" ] || { echo "IMAGE_MISSING" >> "$STATUS"; echo "DONE $(date +%T)" >> "$STATUS"; exit 3; }
echo "IMAGE_SIZE=$(du -h "$OUT/$VM_NAME" | cut -f1)" >> "$STATUS"

if tr -d '\000' < "$CONSOLE" 2>/dev/null | grep -q "$DONE_MARKER"; then
  echo "CLOUD_INIT_DONE=yes" >> "$STATUS"
  if tr -d '\000' < "$CONSOLE" 2>/dev/null | grep -qiE "package_update_upgrade_install.*fail|dnf.*error|failed to install"; then
    echo "WARN=cloud-init zgłosił problem z instalacją pakietu (nie-krytyczne, jeśli smoke OK)" >> "$STATUS"
  fi
  echo "RESULT=OK (zweryfikuj smoke-testem przed promocją)" >> "$STATUS"
  status_rc=0
else
  echo "CLOUD_INIT_DONE=no" >> "$STATUS"
  echo "RESULT=INCOMPLETE — cloud-init nie zgłosił zakończenia; NIE promować" >> "$STATUS"
  tr -d '\000' < "$CONSOLE" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -iE "fail|error|cannot|unable" | tail -5 >> "$STATUS" || true
  status_rc=5
fi
echo "DONE $(date +%T)" >> "$STATUS"
exit $status_rc
