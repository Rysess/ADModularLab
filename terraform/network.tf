# First usable AZ, not an assumed "<region>a".
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "lab" {
  cidr_block           = local.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${local.lab.name}-vpc" }
}

resource "aws_subnet" "lab" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.subnet_cidr
  map_public_ip_on_launch = true
  # Chosen once by ./lab from AWS spot placement scores; '' = first zone.
  availability_zone = (try(local.lab.availability_zone, "") != ""
    ? local.lab.availability_zone
  : data.aws_availability_zones.available.names[0])
  tags = { Name = "${local.lab.name}-subnet" }
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.lab.name}-igw" }
}

# Routes are separate resources, never inline: a route table with inline routes
# owns its whole route list and deletes the VPN return route on the next apply.
resource "aws_route_table" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = { Name = "${local.lab.name}-rt" }
}

resource "aws_route" "internet" {
  route_table_id         = aws_route_table.lab.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.lab.id
}

resource "aws_route_table_association" "lab" {
  subnet_id      = aws_subnet.lab.id
  route_table_id = aws_route_table.lab.id
}

# Return path for VPN clients; needs source_dest_check = false on the host.
resource "aws_route" "vpn_clients" {
  count                  = length(local.vpn_keys) > 0 ? 1 : 0
  route_table_id         = aws_route_table.lab.id
  destination_cidr_block = local.vpn_client_cidr
  network_interface_id   = aws_instance.host[local.vpn_keys[0]].primary_network_interface_id
}
