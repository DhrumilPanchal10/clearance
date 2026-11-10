variable "region" {
  type    = string
  default = "us-east-1"
}

variable "use_localstack" {
  type        = bool
  default     = true
  description = "Target LocalStack (free, offline). Set false only with AWS free-tier credits."
}

variable "artifacts_bucket" {
  type    = string
  default = "clearance-artifacts-dev"
}
