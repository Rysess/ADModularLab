terraform {
  required_version = ">= 1.6.0"

  # Path supplied per lab by ./lab (labs/<name>/.lab/terraform.tfstate), so every
  # lab has its own state and any number can be applied side by side.
  backend "local" {}

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    tls     = { source = "hashicorp/tls", version = "~> 4.0" }
    local   = { source = "hashicorp/local", version = "~> 2.0" }
    http    = { source = "hashicorp/http", version = "~> 3.4" }
    random  = { source = "hashicorp/random", version = "~> 3.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

provider "aws" {
  region = local.lab.region

  # Every resource carries the lab tags; the expiry Lambda acts on ExpiresAt.
  default_tags {
    tags = local.lab_tags
  }
}
