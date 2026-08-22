# Terraform (zablokowany na tym hoście — patrz decyzja 2026-08-22)

Ta konfiguracja (provider `dmacvicar/libvirt`) opisuje kolektory jako domeny
libvirt. **Nie jest na ścieżce krytycznej**: na tej stacji provider łączy się
z `qemu:///system` niezależnie od `uri = "qemu:///session"` i od
`LIBVIRT_DEFAULT_URI` (pula i domeny lądują w systemowym libvirtd), a NAT
`default` na `qemu:///system` nie przepuszcza egressu z gości bez zmian w
firewalld (wymagają roota).

Zgodnie z Bramką G1 planu (`docs/plans/7-stack-transformation.md`) przeszliśmy
na wariant **Ansible + `virt-install` na `qemu:///session` + passt**
(`ansible/playbooks/provision.yml`) — bezrootowy, ze sprawdzonym egressem
(Etap 0). Terraform wraca do gry, gdy albo provider zacznie honorować
`qemu:///session`, albo host dostanie działający NAT na `qemu:///system`
(poprawka firewalld).
