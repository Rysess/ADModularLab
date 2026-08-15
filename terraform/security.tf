locals {
  internal_cidrs = [local.vpc_cidr, local.vpn_client_cidr]
}

resource "aws_security_group" "windows" {
  name        = "${local.lab.name}-windows-sg"
  description = "Lab-internal any/any, plus WinRM and RDP from the operator."
  vpc_id      = aws_vpc.lab.id

  ingress {
    description = "Lab-internal traffic (VPC and VPN clients)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = local.internal_cidrs
  }
  ingress {
    description = "WinRM"
    from_port   = 5985
    to_port     = 5986
    protocol    = "tcp"
    cidr_blocks = local.operator_cidrs
  }
  ingress {
    description = "RDP"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = local.operator_cidrs
  }
  egress {
    description = "Outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.lab_tags, { Name = "${local.lab.name}-windows-sg" })
}

resource "aws_security_group" "linux" {
  name        = "${local.lab.name}-linux-sg"
  description = "Lab-internal any/any, plus SSH and Elastic from the operator."
  vpc_id      = aws_vpc.lab.id

  ingress {
    description = "Lab-internal traffic (VPC and VPN clients)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = local.internal_cidrs
  }
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = local.operator_cidrs
  }
  ingress {
    description = "Kibana"
    from_port   = 5601
    to_port     = 5601
    protocol    = "tcp"
    cidr_blocks = local.operator_cidrs
  }
  ingress {
    description = "Elasticsearch"
    from_port   = 9200
    to_port     = 9200
    protocol    = "tcp"
    cidr_blocks = local.operator_cidrs
  }
  egress {
    description = "Outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.lab_tags, { Name = "${local.lab.name}-linux-sg" })
}

resource "aws_security_group" "host_expose" {
  for_each    = local.exposed_hosts
  name        = "${local.lab.name}-${each.key}-expose"
  description = "Operator-facing ports for ${each.key}"
  vpc_id      = aws_vpc.lab.id

  dynamic "ingress" {
    for_each = each.value.expose_ports
    content {
      description = "${upper(ingress.value.proto)}/${ingress.value.port} from the operator"
      from_port   = ingress.value.port
      to_port     = ingress.value.port
      protocol    = ingress.value.proto
      cidr_blocks = local.operator_cidrs
    }
  }
  egress {
    description = "Outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.lab_tags, { Name = "${local.lab.name}-${each.key}-expose" })
}
