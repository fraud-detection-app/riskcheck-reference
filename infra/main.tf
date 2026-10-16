# A tiny Terraform stack that creates NOTHING in any cloud.
#
# terraform_data is built into Terraform: it only remembers a value in the state file.
# That is enough to practise the real pipeline (fmt, validate, plan per environment,
# apply through approvals) with no account, no keys and no cost.
#
# In a real stack this resource would be an S3 bucket, a Lambda function, a log group ...
# and the state file would live in an S3 bucket (week 13b), not on the runner.

terraform {
  required_version = ">= 1.15"
}

resource "terraform_data" "settings" {
  input = {
    env      = var.env
    replicas = var.replicas
    log_days = var.log_days
  }
}

output "name" {
  description = "The name every real resource of this environment would carry."
  value       = "finrisk-${var.env}"
}

output "settings" {
  description = "The settings this environment was applied with."
  value       = terraform_data.settings.output
}
