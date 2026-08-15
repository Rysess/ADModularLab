locals {
  windows_version = tostring(try(local.defaults.windows_version, "2022"))
  ubuntu_release  = tostring(try(local.defaults.ubuntu_release, "22.04"))
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd*/ubuntu-*-${local.ubuntu_release}-amd64-server-*"]
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
    values = ["Windows_Server-${local.windows_version}-English-Full-Base-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Only a pinned AMI triggers replacement; drift of the "latest" data sources is
# ignored so a new upstream image never rebuilds a live lab.
resource "terraform_data" "ami_pin" {
  for_each = local.hosts
  input    = try(each.value.ami, "")
}

resource "aws_instance" "host" {
  for_each = local.hosts

  ami = try(each.value.ami,
    each.value.os == "windows" ? data.aws_ami.windows.id : data.aws_ami.ubuntu.id
  )
  instance_type = try(each.value.instance_type,
    each.value.os == "windows"
    ? local.defaults.windows_instance_type
    : local.defaults.linux_instance_type
  )

  subnet_id         = aws_subnet.lab.id
  private_ip        = try(each.value.private_ip, null)
  key_name          = aws_key_pair.lab_key.key_name
  get_password_data = each.value.os == "windows"
  source_dest_check = try(each.value.source_dest_check, true)

  vpc_security_group_ids = compact([
    each.value.os == "windows" ? aws_security_group.windows.id : aws_security_group.linux.id,
    contains(keys(local.exposed_hosts), each.key) ? aws_security_group.host_expose[each.key].id : "",
  ])

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = try(local.lab.imdsv1_enabled, false) ? "optional" : "required"
  }

  root_block_device {
    volume_type = "gp3"
    encrypted   = true
    volume_size = try(each.value.disk_gb,
      each.value.os == "windows"
      ? local.defaults.windows_disk_gb
      : local.defaults.linux_disk_gb
    )
  }

  # No credential in user-data: it is readable from IMDS.
  user_data = each.value.os == "windows" ? file("${path.module}/templates/winrm.ps1") : null

  tags = merge(local.lab_tags, {
    Name    = "${local.lab.name}-${each.key}"
    LabHost = each.key
    Os      = each.value.os
    LabRole = try(each.value.role, "standalone")
    Modules = join(",", local.host_modules[each.key])
  })

  lifecycle {
    ignore_changes       = [ami, user_data]
    replace_triggered_by = [terraform_data.ami_pin[each.key]]
  }
}
