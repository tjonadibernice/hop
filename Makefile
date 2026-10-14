.PHONY: up down api web lint test build format format-check install migrate migration seed check-embeds worker ingest check test-db

up:
	docker compose up -d

down:
	docker compose down

api:
	cd backend && uv run uvicorn app.main:app --reload

web:
	cd frontend && npm run dev

install:
	cd backend && uv sync
	cd frontend && npm install

migrate:
	cd backend && uv run alembic upgrade head

migration:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

seed:
	cd backend && uv run python -m scripts.seed_pages

check-embeds:
	cd backend && uv run python -m scripts.check_embeddable

worker:
	cd backend && uv run taskiq worker app.worker:broker

# URL list to queue; override with: make ingest f=path/to/list.txt (relative to backend/)
f ?= scripts/sources.txt
ingest:
	cd backend && uv run python -m scripts.enqueue_urls $(f)

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

test:
	cd backend && uv run pytest

build:
	cd frontend && npm run build

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format

format-check:
	cd backend && uv run ruff format --check .
	cd frontend && npx prettier --check .

check: lint format-check test build

test-db:
	docker compose exec db sh -c 'createdb -U "$$POSTGRES_USER" hop_test'