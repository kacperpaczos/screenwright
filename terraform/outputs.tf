output "collector_ssh" {
  description = "Endpointy SSH kolektorów (passt → 127.0.0.1:<port>)"
  value       = { for k, spec in var.collectors : k => "127.0.0.1:${spec.ssh_port}" }
}

output "inventory_file" {
  value = local_file.ansible_inventory.filename
}
