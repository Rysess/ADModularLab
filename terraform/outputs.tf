output "lab_name" {
  description = "Lab name, used as the EC2 tag the dynamic inventory filters on."
  value       = local.lab.name
}

output "region" {
  description = "AWS region the lab is deployed in."
  value       = local.lab.region
}

output "expires_at" {
  description = "Value of the ExpiresAt tag on every lab resource (RFC3339)."
  value       = local.expires_at
}

output "domain_admin_password" {
  description = "Password for the lab's domain admin account."
  value       = random_password.lab["domain_admin"].result
  sensitive   = true
}

output "dsrm_password" {
  description = "Directory Services Restore Mode password set during promotion."
  value       = random_password.lab["dsrm"].result
  sensitive   = true
}

output "lab_user_password" {
  description = "Shared password for the generated LabUser* accounts."
  value       = random_password.lab["lab_user"].result
  sensitive   = true
}

output "elastic_password" {
  description = "Password for the Elasticsearch/Kibana 'elastic' superuser."
  value       = random_password.lab["elastic"].result
  sensitive   = true
}

output "monitor_password" {
  description = "Password for the read-only Elasticsearch 'monitor' user."
  value       = random_password.lab["monitor"].result
  sensitive   = true
}

output "sql_password" {
  description = "Password for the SQL Server 'svc_labapp' login."
  value       = random_password.lab["sql"].result
  sensitive   = true
}

output "trust_password" {
  description = "Shared secret used when both sides of a lab trust are created."
  value       = random_password.lab["trust"].result
  sensitive   = true
}

output "child_dc_password" {
  description = "Password for the account the child_dc role promotes with."
  value       = random_password.lab["child_dc"].result
  sensitive   = true
}

output "windows_admin_passwords" {
  description = "Local Administrator password per Windows host. Empty for hosts booted from a snapshot AMI."
  value       = local.windows_admin_passwords
  sensitive   = true
}

output "ssh_private_key_path" {
  description = "Path to the generated lab SSH private key."
  value       = local_file.private_key.filename
}

output "elastic_private_ip" {
  description = "Private IP of the edr_server host, or empty if the lab has none."
  value       = length(local.elastic_keys) > 0 ? aws_instance.host[local.elastic_keys[0]].private_ip : ""
}

output "vpn_public_ip" {
  description = "Public IP of the vpn host, or empty if the lab has none."
  value       = length(local.vpn_keys) > 0 ? aws_instance.host[local.vpn_keys[0]].public_ip : ""
}

output "hosts" {
  description = "Deployed hosts keyed by name, with addressing, role and applied modules."
  value = { for k, h in local.hosts : k => {
    public_ip  = aws_instance.host[k].public_ip
    private_ip = aws_instance.host[k].private_ip
    os         = h.os
    role       = try(h.role, "standalone")
    modules    = local.host_modules[k]
  } }
}
