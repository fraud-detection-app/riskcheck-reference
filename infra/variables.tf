# The three settings of one environment. Each envs/<name>.tfvars file gives them values.

variable "env" {
  description = "Which environment this is."
  type        = string

  # A typo such as "staging" stops terraform BEFORE it plans anything.
  validation {
    condition     = contains(["dev", "sit", "pre-prod", "prod"], var.env)
    error_message = "env must be one of: dev, sit, pre-prod, prod."
  }
}

variable "replicas" {
  description = "How many copies of the service would run (a made-up setting for this lab)."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 1
    error_message = "replicas must be at least 1."
  }
}

variable "log_days" {
  description = "How many days logs would be kept (a made-up setting for this lab)."
  type        = number
  default     = 7
}
