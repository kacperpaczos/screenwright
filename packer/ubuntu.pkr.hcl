# Packer: golden image Ubuntu 24.04 — deklaratywny odpowiednik vm/build/seed-ubuntu.sh.
#
# Model: cloud image jako dysk bazowy + NoCloud seed (cidata CD). cloud-init
# instaluje ubuntu-desktop + gnome-software + snap-store + qemu-guest-agent,
# ustawia autologin użytkownika `test`, i GASI maszynę (power_state: poweroff).
# Packer z `communicator = "none"` czeka na to samo-zgaszenie i zabiera qcow2.
#
# Sieć: Packer uruchamia qemu WPROST z user-mode (SLIRP) — ma egress bez passt
# (obchodzi problem NAT-u qemu:///system z tego hosta). Nie wymaga roota (kvm 0666).

packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = ">= 1.1.0"
    }
  }
}

variable "cloud_image" {
  type        = string
  description = "cloud image Ubuntu (dysk bazowy)"
}

variable "seed_dir" {
  type        = string
  description = "katalog z NoCloud user-data + meta-data (render UbuntuBuilder)"
}

variable "output_dir" {
  type        = string
  description = "gdzie Packer złoży golden qcow2"
}

variable "disk_size" {
  type    = string
  default = "25G"
}

variable "memory" {
  type    = number
  default = 4096
}

variable "cpus" {
  type    = number
  default = 2
}

source "qemu" "ubuntu" {
  # dysk bazowy = cloud image (nie instalator ISO)
  iso_url        = var.cloud_image
  iso_checksum   = "none"
  disk_image     = true
  disk_size      = var.disk_size
  format         = "qcow2"
  disk_interface = "virtio"
  net_device     = "virtio-net"

  accelerator = "kvm"
  headless    = true
  memory      = var.memory
  cpus        = var.cpus

  # NoCloud seed jako etykietowany CD 'cidata' — cloud-init go czyta
  cd_files = ["${var.seed_dir}/user-data", "${var.seed_dir}/meta-data"]
  cd_label = "cidata"

  # cloud-init robi wszystko i gasi maszynę; Packer nie loguje się po SSH
  communicator     = "none"
  shutdown_timeout = "50m"
  boot_wait        = "5s"

  output_directory = var.output_dir
  vm_name          = "ubuntu-24.04.qcow2"

  # log konsoli szeregowej do podglądu + KANAŁ qemu-guest-agent.
  # Bez virtio-serial `org.qemu.guest_agent.0` postinst pakietu qemu-guest-agent
  # pada, a cloud-init przerywa całą instalację przed konfiguracją SSH/usera i
  # markerem „done" — obraz wychodzi niekompletny (SSH nie odpowiada). Kanał
  # dokładamy tak jak robi to virt-install przy uruchamianiu golden.
  qemuargs = [
    ["-serial", "file:${var.output_dir}/console.log"],
    ["-chardev", "socket,path=${var.output_dir}/qga.sock,server=on,wait=off,id=qga0"],
    ["-device", "virtio-serial"],
    ["-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0"],
  ]
}

build {
  sources = ["source.qemu.ubuntu"]
}
