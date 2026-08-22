# Maszyny per profil dla screenwright (docs/plans/7-stack-transformation.md).
# Domyślnie qemu:///system: sieć NAT `default`, adresy z dzierżawy DHCP, bez passt.

variable "libvirt_uri" {
  # DECYZJA 2026-08-22: qemu:///session + passt. Na tej stacji NAT `default` na
  # qemu:///system NIE przepuszcza egressu z gości (firewalld/WiFi uplink;
  # ping 8.8.8.8 = 100% loss, TCP:443 FAIL, DNS działa tylko przez dnsmasq).
  # Naprawa NAT-u wymaga roota (firewalld). passt jest usermode, bezrootowy i
  # sprawdzony w Etapie 0. qemu:///system zostaje celem docelowym po poprawce
  # firewalld na hoście.
  description = "URI libvirt (session+passt domyślnie; patrz komentarz)"
  type        = string
  default     = "qemu:///session"
}

variable "pool_name" {
  type    = string
  default = "screenwright"
}

variable "pool_path" {
  description = "Katalog puli; w trybie session leży w HOME (session libvirtd nie ma praw do /var/lib/libvirt)"
  type        = string
  default     = "~/.local/share/screenwright/images/pool"
}

variable "ssh_public_key_file" {
  description = "Klucz publiczny wstrzykiwany przez cloud-init (ten sam, co w golden images)"
  type        = string
  default     = "~/.ssh/screenwright_ubuntu.pub"
}

variable "guest_user" {
  type    = string
  default = "test"
}

variable "collectors" {
  description = "Profil collector-<distro>: lekka maszyna bez desktopu, z oficjalnego cloud image'a"
  type = map(object({
    image    = string # URL albo ścieżka lokalna do qcow2/img
    ssh_port = number # port na 127.0.0.1 przekierowany przez passt do 22 gościa (unikalny per kolektor)
    memory   = optional(number, 2048)
    vcpu     = optional(number, 2)
    disk     = optional(number, 21474836480) # 20 GiB — katalogi + flatpak appstream + snapd
  }))
  default = {
    fedora = {
      image    = "https://download.fedoraproject.org/pub/fedora/linux/releases/44/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2"
      ssh_port = 2201
    }
    ubuntu = {
      image    = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
      ssh_port = 2202
    }
  }
}
