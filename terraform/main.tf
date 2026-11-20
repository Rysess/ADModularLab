locals {
  # Everything is decided by ./lab before Terraform runs: defaults applied,
  # sizes chosen, module vars expanded. This file only maps it to resources.
  cfg      = jsondecode(file(var.config_file))
  lab      = local.cfg.lab
  net      = local.cfg.network
  defaults = local.cfg.defaults
  hosts    = { for h in local.cfg.hosts : h.name => h }

  windows_hosts = { for k, h in local.hosts : k => h if h.os == "windows" }
  elastic_keys  = [for k, h in local.hosts : k if contains(h.modules, "edr_server")]
  vpn_keys      = [for k, h in local.hosts : k if contains(h.modules, "vpn")]
  exposed_hosts = { for k, h in local.hosts : k => h if length(h.expose_ports) > 0 }

  vpc_cidr        = local.net.vpc_cidr
  subnet_cidr     = local.net.subnet_cidr
  vpn_client_cidr = local.net.vpn_client_cidr
  vpc_dns_ip      = cidrhost(local.vpc_cidr, 2) # the Amazon-provided resolver

  expires_at      = local.lab.expires_at # RFC3339, or "never"
  expires_enabled = local.expires_at != "never" && local.lab.expires_enabled

  lab_tags = {
    Lab       = local.lab.name
    ExpiresAt = local.expires_at
    ManagedBy = "adlab"
  }
}

data "http" "my_ip" {
  count = length(var.operator_cidrs) + length(local.lab.operator_cidrs) == 0 ? 1 : 0
  url   = "https://checkip.amazonaws.com"

  retry {
    attempts     = 5
    min_delay_ms = 1000
  }

  lifecycle {
    postcondition {
      condition     = can(cidrhost("${chomp(self.response_body)}/32", 0))
      error_message = "Could not detect a public IP; set lab.allow_from: [x.x.x.x/32]."
    }
  }
}

locals {
  operator_cidrs = distinct(concat(
    var.operator_cidrs,
    local.lab.operator_cidrs,
    [for d in data.http.my_ip : "${chomp(d.response_body)}/32"],
  ))
}
