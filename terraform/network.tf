resource "aws_vpc" "lab" {
  cidr_block           = local.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(local.lab_tags, { Name = "${local.lab.name}-vpc" })
}

resource "aws_subnet" "lab" {
  vpc_id                  = aws_vpc.lab.id
  cidr_block              = local.subnet_cidr
  map_public_ip_on_launch = true
  availability_zone       = "${local.lab.region}a"
  tags                    = merge(local.lab_tags, { Name = "${local.lab.name}-subnet" })
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id
  tags   = merge(local.lab_tags, { Name = "${local.lab.name}-igw" })
}

resource "aws_route_table" "lab" {
  vpc_id = aws_vpc.lab.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }
  tags = merge(local.lab_tags, { Name = "${local.lab.name}-rt" })
}

resource "aws_route_table_association" "lab" {
  subnet_id      = aws_subnet.lab.id
  route_table_id = aws_route_table.lab.id
}

# Return path for VPN clients. Requires source_dest_check = false on the host.
resource "aws_route" "vpn_clients" {
  count                  = length(local.vpn_keys) > 0 ? 1 : 0
  route_table_id         = aws_route_table.lab.id
  destination_cidr_block = local.vpn_client_cidr
  network_interface_id   = aws_instance.host[local.vpn_keys[0]].primary_network_interface_id
}
