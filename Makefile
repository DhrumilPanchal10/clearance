.DEFAULT_GOAL := help
.PHONY: help install up temporal worker payer api test lint eval-smoke eval-full demo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install deps (uv) + dev group
	uv sync --extra ml --group dev

up: ## Start Postgres (pgvector) + Redis
	docker compose up -d

temporal: ## Start Temporal dev server (requires Temporal CLI)
	temporal server start-dev

worker: ## Run the Temporal worker
	uv run python -m clearance.workflows.worker

payer: ## Run the payer service (separate FastAPI app)
	uv run uvicorn payer_service.app:app --port 8081 --reload

api: ## Run the Clearance API
	uv run uvicorn clearance.api.main:app --port 8080 --reload

test: ## Run the test suite offline
	OFFLINE=1 uv run pytest -q

lint: ## ruff + mypy --strict
	uv run ruff check src tests scripts payer_service
	uv run ruff format --check src tests scripts payer_service
	uv run mypy

eval-smoke: ## Run the offline eval subset
	OFFLINE=1 uv run python -m evals.run --smoke

eval-full: ## Run the full eval suite
	uv run python -m evals.run

demo: ## Run the end-to-end demo
	uv run python -m scripts.demo
