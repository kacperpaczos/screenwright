provider "libvirt" {
  uri = var.libvirt_uri
}

locals {
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key_file)))
}

resource "libvirt_pool" "screenwright" {
  name = var.pool_name
  type = "dir"
  target {
    path = pathexpand(var.pool_path)
  }
}

# Obraz bazowy per dystrybucja (cloud image) — wgrywany do puli raz, klony robią na nim backing.
resource "libvirt_volume" "base" {
  for_each = var.collectors
  name     = "base-${each.key}.qcow2"
  pool     = libvirt_pool.screenwright.name
  source   = each.value.image
  format   = "qcow2"
}

resource "libvirt_volume" "collector_disk" {
  for_each       = var.collectors
  name           = "collector-${each.key}.qcow2"
  pool           = libvirt_pool.screenwright.name
  base_volume_id = libvirt_volume.base[each.key].id
  size           = each.value.disk
  format         = "qcow2"
}

resource "libvirt_cloudinit_disk" "collector" {
  for_each = var.collectors
  name     = "collector-${each.key}-cloudinit.iso"
  pool     = libvirt_pool.screenwright.name
  user_data = templatefile("${path.module}/cloud-init/user-data.yaml.tftpl", {
    hostname       = "collector-${each.key}"
    guest_user     = var.guest_user
    ssh_public_key = local.ssh_public_key
  })
  meta_data = "instance-id: collector-${each.key}\nlocal-hostname: collector-${each.key}\n"
}

resource "libvirt_domain" "collector" {
  for_each  = var.collectors
  name      = "collector-${each.key}"
  memory    = each.value.memory
  vcpu      = each.value.vcpu
  cloudinit = libvirt_cloudinit_disk.collector[each.key].id
  autostart = false

  cpu {
    mode = "host-passthrough"
  }

  disk {
    volume_id = libvirt_volume.collector_disk[each.key].id
  }

  # Sieć: passt (usermode, bezrootowy egress) wstrzykiwana przez XSLT niżej —
  # provider nie zna backendu passt, więc dodajemy interfejs transformacją XML.
  xml {
    xslt = templatefile("${path.module}/passt.xsl.tftpl", { ssh_port = each.value.ssh_port })
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }

  graphics {
    type           = "vnc"
    listen_type    = "address"
    listen_address = "127.0.0.1"
  }
}

# Inventory dla Ansible renderowane przez Terraform — bez własnego skryptu.
resource "local_file" "ansible_inventory" {
  filename        = "${path.module}/../ansible/inventory/terraform.ini"
  file_permission = "0644"
  content = templatefile("${path.module}/inventory.ini.tftpl", {
    collectors = var.collectors
    guest_user = var.guest_user
  })
  depends_on = [libvirt_domain.collector]
}
