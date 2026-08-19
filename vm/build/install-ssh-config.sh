#!/usr/bin/env bash
# install-ssh-config.sh — dopisuje alias 'screenwright-ubuntu' do ~/.ssh/config.
#
# Użycie:
#   vm/build/install-ssh-config.sh
#
# Alias umożliwia interaktywny `ssh screenwright-ubuntu` po lookupie IP przez
# `virsh domifaddr` — runner zamienia HostName dynamicznie przez opcję `-J`
# albo przez `ssh -i <key> test@<ip>`. Skrypt dodaje też domyślny wpis z
# IdentityFile + StrictHostKeyChecking=no dla wygody operatorów.
set -euo pipefail

CONFIG="$HOME/.ssh/config"
MARKER="# screenwright-managed: screenwright-ubuntu"

if [[ -f "$CONFIG" ]] && grep -qF "$MARKER" "$CONFIG"; then
    echo "OK: alias już zainstalowany w $CONFIG"
    exit 0
fi

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$CONFIG"
chmod 600 "$CONFIG"

cat >> "$CONFIG" <<'EOF'

# screenwright-managed: screenwright-ubuntu
Host screenwright-ubuntu
    User test
    IdentityFile ~/.ssh/screenwright_ubuntu
    IdentitiesOnly yes
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ServerAliveInterval 30
    ServerAliveCountMax 6
# end screenwright-managed: screenwright-ubuntu
EOF

echo "OK: dopisano alias do $CONFIG"