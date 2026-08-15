resource "tls_private_key" "lab_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lab_key" {
  key_name   = "${local.lab.name}-key"
  public_key = tls_private_key.lab_key.public_key_openssh
  tags       = local.lab_tags
}

resource "local_file" "private_key" {
  content         = tls_private_key.lab_key.private_key_pem
  filename        = "${path.module}/lab-key.pem"
  file_permission = "0600"
}

locals {
  # Alphanumeric only: handed to PowerShell, sqlcmd and WinRM basic auth.
  password_lengths = {
    dsrm         = 24
    domain_admin = 24
    lab_user     = 16
    elastic      = 20
    monitor      = 20
    sql          = 20
    trust        = 24
    child_dc     = 20
  }
}

resource "random_password" "lab" {
  for_each = local.password_lengths

  length  = each.value
  special = false

  # AD and SQL enforce complexity; without minimums an all-lowercase result
  # is possible and account creation fails.
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}
