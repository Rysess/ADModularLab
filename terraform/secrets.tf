locals {
  # A snapshot AMI is not sysprepped, so EC2 publishes no password data.
  windows_admin_passwords = {
    for k, h in local.windows_hosts : k => (
      aws_instance.host[k].password_data != ""
      ? rsadecrypt(aws_instance.host[k].password_data, tls_private_key.lab_key.private_key_pem)
      : ""
    )
  }

  lab_secrets = {
    domain_name          = local.lab_domain
    domain_admin_user    = local.lab.domain_admin
    domain_admin_display = try(local.lab.domain_admin_display, local.lab.domain_admin)
    domain_admin_pw      = random_password.lab["domain_admin"].result
    dsrm_password        = random_password.lab["dsrm"].result
    lab_user_password    = random_password.lab["lab_user"].result
    elastic_password     = random_password.lab["elastic"].result
    monitor_password     = random_password.lab["monitor"].result
    sql_password         = random_password.lab["sql"].result
    trust_password       = random_password.lab["trust"].result
    child_dc_password    = random_password.lab["child_dc"].result
    lab_ssh_key          = abspath(local_file.private_key.filename)
    host_admin_passwords = local.windows_admin_passwords
  }

  # Both CIDR and network/netmask: OpenVPN wants the latter and Ansible has no
  # netaddr filters available.
  lab_facts = {
    lab_name           = local.lab.name
    lab_region         = local.lab.region
    vpc_cidr           = local.vpc_cidr
    vpc_network        = cidrhost(local.vpc_cidr, 0)
    vpc_netmask        = cidrnetmask(local.vpc_cidr)
    vpc_dns_ip         = local.vpc_dns_ip
    subnet_cidr        = local.subnet_cidr
    vpn_client_cidr    = local.vpn_client_cidr
    vpn_client_network = cidrhost(local.vpn_client_cidr, 0)
    vpn_client_netmask = cidrnetmask(local.vpn_client_cidr)
  }
}

resource "local_file" "lab_secrets" {
  filename        = "${path.module}/../ansible/group_vars/all/lab_secrets.yml"
  content         = yamlencode(local.lab_secrets)
  file_permission = "0600"
}

resource "local_file" "lab_facts" {
  filename        = "${path.module}/../ansible/group_vars/all/lab_facts.yml"
  content         = yamlencode(local.lab_facts)
  file_permission = "0644"
}

locals {
  # The domain a host serves or joins. A child_dc serves its own domain like
  # any other host; its parent is the domain minus the first label.
  host_domain = {
    for k, h in local.hosts : k => try(h.domain, (
      try(h.role, "") == "child_dc"
      ? "${try(h.child_label, local.lab_child_label)}.${local.lab_domain}"
      : local.lab_domain
    ))
  }

  # ansible_password must be a host var: under delegate_to a group_vars
  # template keyed on inventory_hostname resolves to the wrong host.
  host_vars = {
    for k, h in local.hosts : k => merge(
      local.host_module_vars[k],
      try(h.vars, {}),
      { domain_name = local.host_domain[k] },
      h.os == "windows" ? { ansible_password = local.windows_admin_passwords[k] } : {}
    )
  }
}

resource "local_file" "host_vars" {
  for_each = { for k, v in local.host_vars : k => v if length(v) > 0 }

  filename        = "${path.module}/../ansible/host_vars/${each.key}.yml"
  content         = yamlencode(each.value)
  file_permission = "0600"
}
