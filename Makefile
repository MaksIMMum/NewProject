-include .env

COMPOSE := docker compose
DB_PORT ?= 5432
LOCAL_DATABASE_URL := $(subst @db:5432,@localhost:$(DB_PORT),$(DATABASE_URL))
s ?=

.DEFAULT_GOAL := help
.PHONY: help env build up down restart logs ps migrate migration seed psql test lint format \
	dev-backend dev-frontend install clean deploy deploy-auth deploy-backend deploy-frontend destroy-auth destroy-backend destroy-frontend add-domain remove-domain infra-lint \
	deploy-reports report-now destroy-reports llm-hello parse deploy-ai destroy-ai \
	infra-fmt infra-validate infra-plan

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(firstword $(MAKEFILE_LIST)) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || (cp .env.example .env && echo "Created .env")

build: env ## Build all images
	$(COMPOSE) build

up: env ## Build and start the whole stack
	$(COMPOSE) up -d --build
	@echo "App:      http://localhost:3000"
	@echo "API docs: http://localhost:8000/api/docs"

down: ## Stop the stack
	$(COMPOSE) down

restart: down up ## Restart the stack

logs: ## Follow logs (optionally: make logs s=backend)
	$(COMPOSE) logs -f $(s)

ps: ## Show running services
	$(COMPOSE) ps

migrate: ## Apply database migrations
	$(COMPOSE) exec backend alembic upgrade head

migration: ## Generate a migration: make migration m="add something" (db must be up)
	@test -n "$(m)" || (echo 'Usage: make migration m="message"' && exit 1)
	cd backend && DATABASE_URL=$(LOCAL_DATABASE_URL) uv run alembic revision --autogenerate -m "$(m)"

seed: ## Insert sample participants and meetings
	$(COMPOSE) exec backend python -m app.seed

psql: ## Open psql in the db container
	$(COMPOSE) exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

test: ## Run backend tests (against the <db>_test database)
	$(COMPOSE) exec backend pytest -v

lint: ## Lint backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint && npx prettier --check .

format: ## Format backend and frontend
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

install: ## Install local dev dependencies (uv + npm)
	cd backend && uv sync
	cd frontend && npm install

dev-backend: env ## Run backend locally with reload (db runs in Docker)
	$(COMPOSE) up -d db
	cd backend && DATABASE_URL=$(LOCAL_DATABASE_URL) uv run alembic upgrade head
	cd backend && DATABASE_URL=$(LOCAL_DATABASE_URL) uv run uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run Vite dev server on http://localhost:5173 (proxies /api to :8000)
	cd frontend && npm run dev

clean: ## Stop the stack and delete the database volume
	$(COMPOSE) down -v

# AWS credentials and settings come from .env; export them only to the recipes below.
AWS_ENV := AWS_ACCESS_KEY_ID="$(AWS_ACCESS_KEY_ID)" AWS_SECRET_ACCESS_KEY="$(AWS_SECRET_ACCESS_KEY)" \
	AWS_SESSION_TOKEN="$(AWS_SESSION_TOKEN)" AWS_REGION="$(AWS_REGION)" \
	PROJECT_NAME="$(or $(PROJECT_NAME),$(APP_NAME))" CORS_ORIGINS_AWS="$(CORS_ORIGINS_AWS)" \
	LAMBDA_MEMORY="$(LAMBDA_MEMORY)" DOMAIN_NAME="$(DOMAIN_NAME)" HOSTED_ZONE_ID="$(HOSTED_ZONE_ID)" \
	GOOGLE_CLIENT_ID="$(GOOGLE_CLIENT_ID)" GOOGLE_CLIENT_SECRET="$(GOOGLE_CLIENT_SECRET)" \
	RECIPIENT_EMAIL="$(RECIPIENT_EMAIL)" SENDER_EMAIL="$(SENDER_EMAIL)" \
	PARSER_MODEL="$(or $(PARSER_MODEL),anthropic.claude-haiku-5-5)" ALERT_EMAIL="$(or $(ALERT_EMAIL),$(RECIPIENT_EMAIL))"

deploy: deploy-backend deploy-frontend ## Deploy the whole app to AWS (after make deploy-auth)

deploy-auth: infra-plan ## [Migrated to Terraform] Plan authentication infrastructure (infra/auth.tf)

deploy-backend: env ## Deploy backend (Lambda) + database (Aurora Serverless) to AWS, see infra/
	@$(AWS_ENV) ./infra/deploy-backend.sh

deploy-reports: infra-plan ## [Migrated to Terraform] Plan reports infrastructure (infra/reports.tf)

report-now: env ## Build a report on demand via SQS: make report-now WEEK=2026-W39
	@$(AWS_ENV) ./infra/report-now.sh $(WEEK)

destroy-reports: ## [Migrated to Terraform] Infrastructure lifecycle managed via HCP Terraform
	@echo "Reports infrastructure is managed via Terraform. Use HCP Terraform or terraform destroy in infra/."

deploy-frontend: env ## Deploy frontend to S3 + CloudFront, wired to the Lambda URL (after deploy-backend)
	@$(AWS_ENV) ./infra/deploy-frontend.sh

add-domain: env ## Attach DOMAIN_NAME from .env to the deployed frontend
	@$(AWS_ENV) ./infra/add-domain.sh

remove-domain: env ## Detach the custom domain and delete its certificate
	@$(AWS_ENV) ./infra/remove-domain.sh

destroy-auth: ## [Migrated to Terraform] Infrastructure lifecycle managed via HCP Terraform
	@echo "Auth infrastructure is managed via Terraform. Use HCP Terraform or terraform destroy in infra/."

destroy-backend: env ## Delete the AWS backend stacks (keeps a final DB snapshot)
	@$(AWS_ENV) ./infra/destroy-backend.sh

destroy-frontend: env ## Delete the S3 bucket, CloudFront distribution and domain certificate
	@$(AWS_ENV) ./infra/destroy-frontend.sh

infra-lint: ## Lint remaining CloudFormation templates
	uvx cfn-lint infra/*.yaml

infra-fmt: ## Format Terraform configuration files in infra/
	@PATH="$(HOME)/.local/bin:$$PATH" terraform -chdir=infra fmt

infra-validate: ## Validate Terraform syntax and configuration in infra/
	@PATH="$(HOME)/.local/bin:$$PATH" terraform -chdir=infra init -backend=false >/dev/null 2>&1 || true
	@PATH="$(HOME)/.local/bin:$$PATH" terraform -chdir=infra validate

infra-plan: env ## Run terraform plan via HCP Terraform
	@$(AWS_ENV) PATH="$(HOME)/.local/bin:$$PATH" terraform -chdir=infra plan

llm-hello: env ## Test Bedrock Anthropic Messages API connectivity from laptop
	@$(AWS_ENV) PATH="$(HOME)/.local/bin:$$PATH" sh -c 'cd backend && uv run python -m app.ai.cli hello'

parse: env ## Parse agenda text on laptop: make parse TEXT="..."
	@$(AWS_ENV) TEXT="$(TEXT)" PATH="$(HOME)/.local/bin:$$PATH" sh -c 'cd backend && uv run python -m app.ai.cli parse'

deploy-ai: infra-plan ## [Migrated to Terraform] Plan AI agenda-parser infrastructure (infra/ai.tf)

destroy-ai: ## [Migrated to Terraform] Infrastructure lifecycle managed via HCP Terraform
	@echo "AI infrastructure is managed via Terraform. Use HCP Terraform or terraform destroy in infra/."
