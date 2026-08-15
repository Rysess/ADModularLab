variable "lab_file" {
  description = "Path to the lab definition YAML, relative to the terraform directory (single source of truth)."
  type        = string
  default     = "../lab.yml"

  validation {
    condition     = can(regex("\\.ya?ml$", var.lab_file))
    error_message = "lab_file must point at a .yml or .yaml file."
  }
}

variable "operator_cidrs" {
  description = "CIDRs allowed to reach management ports (WinRM, RDP, SSH, Kibana). Empty = detect this machine's public IP."
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
