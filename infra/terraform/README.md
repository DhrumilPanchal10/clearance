# Infrastructure (Terraform)

Honest-by-default IaC: it provisions ECR repositories and an S3 artifacts bucket
against **LocalStack**, so `terraform apply` is free and offline.

```bash
# LocalStack (default) — costs nothing
docker run -d -p 4566:4566 localstack/localstack
terraform init
terraform apply

# Real AWS — only with free-tier credits
terraform apply -var use_localstack=false
```

Compute (RDS, Redis, ECS/Fargate, Temporal) is **referenced, not applied** — see
the comments in `main.tf`. For demos, the `docker-compose.full.yml` stack runs
the whole system locally; for a hosted demo, a single small VM running the
containers plus the Temporal dev server is enough.
