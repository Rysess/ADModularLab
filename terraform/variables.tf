variable "config_file" {
  description = "Canonical lab definition written by ./lab (labs/<name>/.lab/resolved.json)."
  type        = string
}

variable "out_dir" {
  description = "The lab's workspace (labs/<name>); every generated file lands under it."
  type        = string
}

variable "operator_cidrs" {
  description = "CIDRs allowed to reach management ports. Empty = lab.allow_from, else this machine's public IP."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for c in var.operator_cidrs : can(cidrhost(c, 0))])
    error_message = "operator_cidrs entries must be valid CIDR blocks, e.g. \"203.0.113.4/32\"."
  }

  validation {
    condition     = !contains(var.operator_cidrs, "0.0.0.0/0")
    error_message = "Refusing 0.0.0.0/0: the lab exposes WinRM and RDP and runs deliberately weak AD configurations."
  }
}

variable "known_admin_passwords" {
  description = "Administrator passwords of hosts restored from a lab snapshot AMI (EC2 publishes none for them). Written by ./lab to a var-file."
  type        = map(string)
  default     = {}
  sensitive   = true
}
