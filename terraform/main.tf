locals {
  cfg      = yamldecode(file("${path.module}/${var.lab_file}"))
  lab      = local.cfg.lab
  defaults = try(local.cfg.defaults, {})
  hosts    = { for h in local.cfg.hosts : h.name => h }

  windows_hosts = { for k, h in local.hosts : k => h if h.os == "windows" }

  # A modules entry is a bare name or { name, vars }.
  host_modules = {
    for k, h in local.hosts : k => [
      for m in try(h.modules, []) : can(tostring(m)) ? tostring(m) : m.name
    ]
  }

  host_module_vars = {
    for k, h in local.hosts : k => merge([
      for m in try(h.modules, []) : try(m.vars, {}) if !can(tostring(m))
    ]...)
  }

  elastic_keys = [for k, mods in local.host_modules : k if contains(mods, "edr_server")]
  vpn_keys     = [for k, mods in local.host_modules : k if contains(mods, "vpn")]

  exposed_hosts = { for k, h in local.hosts : k => h if length(try(h.expose_ports, [])) > 0 }

  vpc_cidr        = "10.0.0.0/16"
  subnet_cidr     = "10.0.1.0/24"
  vpn_client_cidr = "10.8.0.0/24"
  vpc_dns_ip      = cidrhost(local.vpc_cidr, 2) # the Amazon-provided resolver

  expires_hours = try(local.lab.expires_hours, 168)
  expires_at    = timeadd(time_static.lab_created.rfc3339, "${local.expires_hours}h")

  lab_tags = {
    Lab       = local.lab.name
    ExpiresAt = local.expires_at
  }
}

# Held in state; run.sh's deploy_stamp resets it, so re-running extends the lease.
resource "time_static" "lab_created" {
  triggers = {
    lab_name      = local.lab.name
    expires_hours = tostring(local.expires_hours)
    deploy_stamp  = var.deploy_stamp
  }
}

data "http" "my_ip" {
  count = length(var.operator_cidrs) == 0 ? 1 : 0
  url   = "https://api.ipify.org"

  retry {
    attempts     = 3
    min_delay_ms = 500
  }

  lifecycle {
    postcondition {
      condition     = can(cidrhost("${chomp(self.response_body)}/32", 0))
      error_message = "Could not detect a public IP; set -var 'operator_cidrs=[\"x.x.x.x/32\"]'."
    }
  }
}

locals {
  operator_cidrs = concat(var.operator_cidrs, [for d in data.http.my_ip : "${chomp(d.response_body)}/32"])
}
