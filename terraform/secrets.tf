locals {
  # A snapshot AMI is not sysprepped, so EC2 publishes no password data.
  # Snapshot AMIs keep the password they were captured with; ./lab records it
  # at snapshot time and passes it back in known_admin_passwords.
  windows_admin_passwords = {
    for k, h in local.windows_hosts : k => (
      aws_instance.host[k].password_data != ""
      ? rsadecrypt(aws_instance.host[k].password_data, tls_private_key.lab_key.private_key_pem)
      : lookup(var.known_admin_passwords, k, "")
    )
  }

  lab_secrets = {
    domain_admin_user    = local.lab.domain_admin
    domain_admin_display = local.lab.domain_admin_display
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

  # network/netmask too: OpenVPN needs it and Ansible has no netaddr filters.
  lab_facts = {
    lab_name           = local.lab.name
    lab_dir            = abspath(var.out_dir)
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

# Inventory-adjacent group_vars: Ansible loads them for this lab's inventory only.
resource "local_file" "lab_secrets" {
  filename        = "${var.out_dir}/inventory/group_vars/all/lab_secrets.yml"
  content         = yamlencode(local.lab_secrets)
  file_permission = "0600"
}

resource "local_file" "lab_facts" {
  filename        = "${var.out_dir}/inventory/group_vars/all/lab_facts.yml"
  content         = yamlencode(local.lab_facts)
  file_permission = "0644"
}

# host_vars (module settings + ansible_password per host) are written by ./lab on
# every run, from lab.yml and the windows_admin_passwords output, so a
# provisioning-only run (--no-infra) never works from stale settings.
