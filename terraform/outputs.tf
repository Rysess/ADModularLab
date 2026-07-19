output "admin_password" {
  value     = random_password.admin.result
  sensitive = true
}
output "monitor_password" {
  value     = random_password.monitor.result
  sensitive = true
}

output "ssh_private_key_path" { value = local_file.private_key.filename }

output "elastic_public_ip" {
  value = length(local.elastic_keys) > 0 ? aws_instance.host[local.elastic_keys[0]].public_ip : ""
}

output "elastic_private_ip" {
  value = length(local.elastic_keys) > 0 ? aws_instance.host[local.elastic_keys[0]].private_ip : ""
}

output "hosts" {
  value = { for k, h in local.hosts : k => {
    public_ip  = aws_instance.host[k].public_ip
    private_ip = aws_instance.host[k].private_ip
    os         = h.os
    role       = try(h.role, "standalone")
    modules    = try(h.modules, [])
  } }
}
