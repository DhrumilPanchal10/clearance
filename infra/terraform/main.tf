# Clearance infrastructure — kept deliberately honest (plan T11.1).
#
# This targets LocalStack by default so `terraform apply` costs nothing and runs
# offline. Point it at real AWS only with free-tier credits by setting
# `use_localstack = false`. It provisions the minimum the platform needs:
# container registries for the three services and an S3 bucket for generated
# letters/packets. The compute (ECS/Fargate, RDS, MemoryDB) is intentionally
# left as commented references rather than a bill waiting to happen.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region                      = var.region
  access_key                  = var.use_localstack ? "test" : null
  secret_key                  = var.use_localstack ? "test" : null
  skip_credentials_validation = var.use_localstack
  skip_requester_charged      = var.use_localstack
  skip_metadata_api_check     = var.use_localstack

  dynamic "endpoints" {
    for_each = var.use_localstack ? [1] : []
    content {
      ecr = "http://localhost:4566"
      s3  = "http://localhost:4566"
      sts = "http://localhost:4566"
    }
  }
}

locals {
  services = ["api", "worker", "payer"]
}

resource "aws_ecr_repository" "service" {
  for_each             = toset(local.services)
  name                 = "clearance/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_s3_bucket" "artifacts" {
  bucket = var.artifacts_bucket
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Compute is referenced, not applied, to keep this free:
#   - RDS Postgres (pgvector) — or the docker-compose Postgres for demos.
#   - MemoryDB / ElastiCache Redis.
#   - ECS Fargate services for api/worker/payer, or a single small VM.
#   - Temporal: the dev server for demos, or a single small VM / Temporal Cloud.
