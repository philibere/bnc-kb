# bnc-kb dev tasks. Run `make` or `make help` for the list.

# Load .env if present and export its vars to recipe commands.
# Config defaults already match docker-compose.yml, so .env is optional.
-include .env
export

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
HOST   ?= 127.0.0.1
PORT   ?= 8000

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(BIN)/activate:
	$(PYTHON) -m venv $(VENV)

.PHONY: install
install: $(BIN)/activate ## Create venv and install the package (with dev extras)
	$(BIN)/pip install -q -e ".[dev]"

.PHONY: up
up: ## Start Postgres and wait until it is healthy
	docker compose up -d --wait

.PHONY: down
down: ## Stop Postgres (keeps the volume)
	docker compose down

.PHONY: migrate
migrate: install up ## Apply SQL migrations (idempotent)
	$(BIN)/python -c "from bnc_kb.db.migrate import apply_migrations; from bnc_kb.config import load_settings; print('applied:', apply_migrations(load_settings().database_url))"

.PHONY: api
api: ## Run the API with reload (assumes db is up and migrated)
	$(BIN)/uvicorn bnc_kb.api.app:app --reload --host $(HOST) --port $(PORT)

.PHONY: dev
dev: up migrate ## Start everything: Postgres, migrations, then the API (foreground)
	@echo "API docs: http://$(HOST):$(PORT)/docs"
	$(MAKE) api

.PHONY: test
test: up install ## Run the full test suite (unit + integration)
	$(BIN)/pytest

.PHONY: test-unit
test-unit: install ## Run unit tests only (no database)
	$(BIN)/pytest -m "not integration"

.PHONY: logs
logs: ## Tail Postgres logs
	docker compose logs -f db

.PHONY: clean
clean: ## Stop Postgres and remove its volume
	docker compose down -v
