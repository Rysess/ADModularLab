locals {
  ubuntu_release = local.defaults.ubuntu_release

  # distinct(): hosts sharing version+edition would collide as map keys.
  windows_image_keys = distinct([
    for k, h in local.windows_hosts : "${h.windows_version}-${h.windows_edition}"
  ])
  windows_images = {
    for key in local.windows_image_keys : key => {
      version = split("-", key)[0]
      edition = title(split("-", key)[1])
    }
  }
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
  for_each    = local.windows_images
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["Windows_Server-${each.value.version}-English-${each.value.edition}-Base-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Only a pinned AMI triggers replacement; "latest" drift never rebuilds a live lab.
resource "terraform_data" "ami_pin" {
  for_each = local.hosts
  input    = each.value.ami
}

resource "aws_instance" "host" {
  for_each = local.hosts

  ami = each.value.ami != "" ? each.value.ami : (
    each.value.os == "windows"
    ? data.aws_ami.windows["${each.value.windows_version}-${each.value.windows_edition}"].id
    : data.aws_ami.ubuntu.id
  )
  instance_type = each.value.instance_type

  subnet_id  = aws_subnet.lab.id
  private_ip = each.value.private_ip != "" ? each.value.private_ip : null
  key_name   = aws_key_pair.lab_key.key_name
  # A snapshot AMI is not sysprepped: EC2 never publishes a password for it.
  get_password_data = each.value.os == "windows" && each.value.ami == ""
  source_dest_check = each.value.source_dest_check

  vpc_security_group_ids = compact([
    each.value.os == "windows" ? aws_security_group.windows.id : aws_security_group.linux.id,
    contains(keys(local.exposed_hosts), each.key) ? aws_security_group.host_expose[each.key].id : "",
  ])

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = local.lab.imdsv1_enabled ? "optional" : "required"
  }

  root_block_device {
    volume_type = "gp3"
    encrypted   = true
    volume_size = each.value.disk_gb
    tags        = merge(local.lab_tags, { Name = "${local.lab.name}-${each.key}" })
  }

  user_data = each.value.os == "windows" ? templatefile("${path.module}/templates/bootstrap.ps1", {
    hostname = each.key
  }) : null

  # Spot by default (lab.spot / host spot: false opts out): ~65% cheaper for
  # Windows. A reclaimed instance is stopped, not lost, and comes back with its
  # disk when capacity returns or on the next ./lab start.
  dynamic "instance_market_options" {
    for_each = each.value.spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        spot_instance_type             = "persistent"
        instance_interruption_behavior = "stop"
      }
    }
  }

  tags = {
    Name    = "${local.lab.name}-${each.key}"
    LabHost = each.key
    Os      = each.value.os
    LabRole = each.value.role
    Modules = join(",", each.value.modules)
  }

  lifecycle {
    # Switching spot/on-demand would rebuild the host; it applies to new or
    # rebuilt hosts only (./lab rebuild).
    ignore_changes       = [ami, user_data, instance_market_options]
    replace_triggered_by = [terraform_data.ami_pin[each.key]]
  }
}

# A fixed address for the VPN endpoint: profiles keep working across stop/start.
resource "aws_eip" "vpn" {
  count    = length(local.vpn_keys) > 0 ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.host[local.vpn_keys[0]].id
  tags     = { Name = "${local.lab.name}-vpn" }
}
