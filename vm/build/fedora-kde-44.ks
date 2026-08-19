# Kickstart dla Fedora KDE 44 — szkielet (M2+).
#
# Użycie:
#   virt-install \
#     --name fedora-kde-44 \
#     --ram 4096 --vcpus 2 --disk size=20 \
#     --location https://download.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/ \
#     --initrd-inject vm/build/fedora-kde-44.ks \
#     --extra-args "inst.ks=file:/fedora-kde-44.ks console=ttyS0,115200" \
#     --graphics none --wait -1 --noreboot
#
# Po kickstarcie VM będzie miała:
#   - KDE desktop, autologin dla użytkownika `test`
#   - qemu-guest-agent (wymagany przez VirshBackend.qemu_agent_exec)
#   - wyłączone blanking / lock screen
#   - wyczyszczone cache paczek
#
# Ten plik jest szkieletem — finalizujemy w M2 (kiedy wracamy do budowy
# od zera zamiast z cloud image).

# --- System ---
install
keyboard --xlayouts=us
lang en_US.UTF-8
timezone Europe/Warsaw --utc
rootpw --lock
user --name=test --password=test --plaintext --gecos="Test User" --groups=wheel
autopart --type=thinp
bootloader --location=mbr
reboot

# --- Paczki ---
%packages
@^kde-desktop-environment
@base-x
qemu-guest-agent
spice-vdagent
%end

# --- Post-install ---
%post --log=/var/log/screenwright-post.log
# Autologin dla `test`.
mkdir -p /etc/sddm.conf.d
cat > /etc/sddm.conf.d/autologin.conf <<EOF
[Autologin]
User=test
Session=plasma.desktop
EOF

# Wyłącz lock screen i blanking.
cat > /home/test/.config/kscreenlockerrc <<EOF
[Daemon]
Autolock=false
EOF

# Włącz qemu-guest-agent.
systemctl enable qemu-guest-agent

# Wyczyść cache paczek.
dnf clean all
%end

# --- Pierwszy boot (kickstart late commands) ---
%post
# Pierwszy boot: stwórz katalog cache, sparsify-friendly.
fstrim -a
%end