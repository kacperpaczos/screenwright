# Packer: golden image Fedora (WS/GNOME lub KDE/Plasma) — wariant cloud-init.
#
# Fedora Cloud Base jako dysk bazowy + NoCloud cidata CD. cloud-init dnf-instaluje
# grupę pulpitu + sklep + qemu-guest-agent, tworzy usera `test` z kluczem i
# autologinem, i GASI maszynę. Uniform z ubuntu.pkr.hcl (bez boot_command Anacondy).
#
# NIEZWERYFIKOWANE buildem (2026-08-22) — build zaplanowany na jutro; instalacja
# grupy @^*-environment przez dnf jest ciężka (~1 GB+) i może wymagać strojenia.

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
  description = "Fedora Cloud Base qcow2 (dysk bazowy)"
}

variable "seed_dir" {
  type        = string
  description = "katalog z NoCloud user-data + meta-data (render build-fedora.sh)"
}

variable "output_dir" {
  type = string
}

variable "vm_name" {
  type        = string
  description = "nazwa wynikowego qcow2, np. fedora-ws.qcow2 / fedora-kde.qcow2"
}

variable "disk_size" {
  type    = string
  default = "20G"
}

variable "memory" {
  type    = number
  default = 4096
}

variable "cpus" {
  type    = number
  default = 2
}

source "qemu" "fedora" {
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

  cd_files = ["${var.seed_dir}/user-data", "${var.seed_dir}/meta-data"]
  cd_label = "cidata"

  communicator     = "none"
  shutdown_timeout = "50m"
  boot_wait        = "5s"

  output_directory = var.output_dir
  vm_name          = var.vm_name

  # log konsoli + kanał qemu-guest-agent (bez niego postinst pada i cloud-init
  # przerywa instalację — patrz ubuntu.pkr.hcl / packer/README.md).
  qemuargs = [
    ["-serial", "file:${var.output_dir}/console.log"],
    ["-chardev", "socket,path=${var.output_dir}/qga.sock,server=on,wait=off,id=qga0"],
    ["-device", "virtio-serial"],
    ["-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0"],
  ]
}

build {
  sources = ["source.qemu.fedora"]
}
