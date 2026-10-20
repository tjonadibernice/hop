.PHONY: up down api web lint test build format format-check install migrate migration seed check-embeds worker scheduler ingest enrich check-links poll-feeds embed ab-report loadtest curate eval-curator check test-db

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

scheduler:
	cd backend && uv run taskiq scheduler app.worker:scheduler

# URL list to queue; override with: make ingest f=path/to/list.txt (relative to backend/)
f ?= scripts/sources.txt
ingest:
	cd backend && uv run python -m scripts.enqueue_urls $(f)

enrich:
	cd backend && uv run python -m scripts.enqueue_enrichment

check-links:
	cd backend && uv run python -m scripts.check_links

poll-feeds:
	cd backend && uv run python -m scripts.poll_feeds

embed:
	cd backend && uv run python -m scripts.embed_pages

ab-report:
	cd backend && uv run python -m scripts.ab_report

curate:
	cd backend && uv run python -m scripts.curate_pages

# Options go in args, e.g.: make eval-curator args="--tag injection --repeat 3"
eval-curator:
	cd backend && uv run python -m scripts.eval_curator $(args)

# Options go in args, e.g.: make loadtest args="--no-queue --users 50"
loadtest:
	cd backend && uv run python -m scripts.load_test $(args)

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