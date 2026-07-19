terraform {
  required_providers {
    aws    = { source = "hashicorp/aws",    version = "~> 5.0" }
    tls    = { source = "hashicorp/tls",    version = "~> 4.0" }
    local  = { source = "hashicorp/local",  version = "~> 2.0" }
    http   = { source = "hashicorp/http",   version = "~> 3.0" }
    random = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

locals {
  cfg      = yamldecode(file("${path.module}/${var.lab_file}"))
  lab      = local.cfg.lab
  defaults = local.cfg.defaults
  hosts    = { for h in local.cfg.hosts : h.name => h }

  windows_hosts = { for k, h in local.hosts : k => h if h.os == "windows" }
  linux_hosts   = { for k, h in local.hosts : k => h if h.os == "linux" }

  all_modules = distinct(flatten([for h in local.cfg.hosts : try(h.modules, [])]))

  dc_ips        = [for k, h in local.hosts : h.private_ip if try(h.role, "") == "dc"]
  dc_private_ip = length(local.dc_ips) > 0 ? local.dc_ips[0] : "10.0.1.10"
  elastic_keys  = [for k, h in local.hosts : k if contains(try(h.modules, []), "edr_server")]

  exposed_hosts = { for k, h in local.hosts : k => h if length(try(h.expose_ports, [])) > 0 }
}

provider "aws" {
  region = local.lab.region
}

data "http" "my_ip" { url = "https://api.ipify.org" }
locals { my_public_ip_cidr = "${chomp(data.http.my_ip.response_body)}/32" }

resource "tls_private_key" "lab_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}
resource "aws_key_pair" "lab_key" {
  key_name   = "${local.lab.name}-key"
  public_key = tls_private_key.lab_key.public_key_openssh
}
resource "local_file" "private_key" {
  content         = tls_private_key.lab_key.private_key_pem
  filename        = "${path.module}/lab-key.pem"
  file_permission = "0600"
}

resource "random_password" "admin" {
  length  = 20
  special = false
}
resource "random_password" "monitor" {
  length  = 20
  special = false
}

resource "aws_vpc" "lab" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = { Name = "${local.lab.name}-vpc" }
}

resource "aws_vpc_dhcp_options" "dns" {
  domain_name         = local.lab.domain
  domain_name_servers = [local.dc_private_ip, "10.0.0.2"]
  tags = { Name = "${local.lab.name}-dhcp" }
}
resource "aws_vpc_dhcp_options_association" "dns" {
  vpc_id          = aws_vpc.lab.id
  dhcp_options_id = aws_vpc_dhcp_options.dns.id
}

resource "aws_subnet" "lab" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${local.lab.region}a"
  tags = { Name = "${local.lab.name}-subnet" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags = { Name = "${local.lab.name}-igw" }
}
resource "aws_route_table" "lab" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
  tags = { Name = "${local.lab.name}-rt" }
}
resource "aws_route_table_association" "lab" {
  subnet_id      = aws_subnet.lab.id
  route_table_id = aws_route_table.lab.id
}

resource "aws_security_group" "windows" {
  name   = "${local.lab.name}-windows-sg"
  vpc_id = aws_vpc.lab.id
  ingress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    from_port = 5985
    to_port = 5986
    protocol = "tcp"
    cidr_blocks = [local.my_public_ip_cidr]
  }
  ingress {
    from_port = 3389
    to_port = 3389
    protocol = "tcp"
    cidr_blocks = [local.my_public_ip_cidr]
  }
  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.lab.name}-windows-sg" }
}

resource "aws_security_group" "linux" {
  name   = "${local.lab.name}-linux-sg"
  vpc_id = aws_vpc.lab.id
  ingress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["10.0.0.0/16"]
  }
  ingress {
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = [local.my_public_ip_cidr]
  }
  ingress {
    from_port = 5601
    to_port = 5601
    protocol = "tcp"
    cidr_blocks = [local.my_public_ip_cidr, "10.0.0.0/16"]
  }
  ingress {
    from_port = 9200
    to_port = 9200
    protocol = "tcp"
    cidr_blocks = [local.my_public_ip_cidr, "10.0.0.0/16"]
  }
  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.lab.name}-linux-sg" }
}

resource "aws_security_group" "host_expose" {
  for_each    = local.exposed_hosts
  name        = "${local.lab.name}-${each.key}-expose"
  description = "Operator-facing ports for ${each.key}"
  vpc_id      = aws_vpc.lab.id

  dynamic "ingress" {
    for_each = each.value.expose_ports
    content {
      from_port   = ingress.value.port
      to_port     = ingress.value.port
      protocol    = ingress.value.proto
      cidr_blocks = [local.my_public_ip_cidr]
    }
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.lab.name}-${each.key}-expose" }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
data "aws_ami" "windows" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "host" {
  for_each = local.hosts

  ami           = each.value.os == "windows" ? data.aws_ami.windows.id : data.aws_ami.ubuntu.id
  instance_type = try(each.value.instance_type,
                      each.value.os == "windows" ? local.defaults.windows_instance_type
                                                  : local.defaults.linux_instance_type)
  subnet_id              = aws_subnet.lab.id
  private_ip             = try(each.value.private_ip, null)
  key_name               = aws_key_pair.lab_key.key_name
  vpc_security_group_ids = compact([
    each.value.os == "windows" ? aws_security_group.windows.id : aws_security_group.linux.id,
    contains(keys(local.exposed_hosts), each.key) ? aws_security_group.host_expose[each.key].id : "",
  ])
  source_dest_check = try(each.value.source_dest_check, true)

  root_block_device {
    volume_type = "gp3"
    volume_size = try(each.value.disk_gb,
                      each.value.os == "windows" ? local.defaults.windows_disk_gb
                                                  : local.defaults.linux_disk_gb)
  }

  user_data = each.value.os == "windows" ? templatefile("${path.module}/templates/winrm.ps1.tftpl", {
    admin_password = random_password.admin.result
  }) : null

  tags = {
    Name    = "${local.lab.name}-${each.key}"
    Os      = each.value.os
    LabRole = try(each.value.role, "standalone")
    Modules = join(",", try(each.value.modules, []))
  }
}

locals {
  win_conn = {
    ansible_connection                   = "winrm"
    ansible_user                         = "Administrator"
    ansible_password                     = random_password.admin.result
    ansible_winrm_transport              = "basic"
    ansible_winrm_server_cert_validation = "ignore"
    ansible_winrm_scheme                 = "http"
    ansible_port                         = 5985
    ansible_winrm_read_timeout_sec       = 60
    ansible_winrm_operation_timeout_sec  = 50
  }
  lin_conn = {
    ansible_connection           = "ssh"
    ansible_user                 = "ubuntu"
    ansible_ssh_private_key_file = abspath(local_file.private_key.filename)
  }

  inventory = {
    all = {
      vars = {
        domain_name        = local.lab.domain
        domain_admin_user  = local.lab.domain_admin
        admin_password     = random_password.admin.result
        monitor_password   = random_password.monitor.result
        aws_region         = local.lab.region
        elastic_private_ip = length(local.elastic_keys) > 0 ? aws_instance.host[local.elastic_keys[0]].private_ip : ""
        dc_private_ip      = local.dc_private_ip
      }
      children = merge(
        {
          windows = {
            vars  = local.win_conn
            hosts = { for k, h in local.windows_hosts : k => {
              ansible_host = aws_instance.host[k].public_ip
              private_ip   = aws_instance.host[k].private_ip
              modules      = try(h.modules, [])
            } }
          }
          linux = {
            vars  = local.lin_conn
            hosts = { for k, h in local.linux_hosts : k => {
              ansible_host = aws_instance.host[k].public_ip
              private_ip   = aws_instance.host[k].private_ip
              modules      = try(h.modules, [])
            } }
          }
          role_dc         = { hosts = { for k, h in local.hosts : k => {} if try(h.role, "") == "dc" } }
          role_member     = { hosts = { for k, h in local.hosts : k => {} if try(h.role, "") == "member" } }
          role_standalone = { hosts = { for k, h in local.hosts : k => {} if try(h.role, "") == "standalone" } }
        },
        { for m in local.all_modules : "mod_${m}" => {
          hosts = { for k, h in local.hosts : k => {} if contains(try(h.modules, []), m) }
        } }
      )
    }
  }
}

resource "local_file" "inventory" {
  filename        = "${path.module}/../ansible/inventory.yml"
  content         = yamlencode(local.inventory)
  file_permission = "0600"
}
