.PHONY: up down api web lint test build format format-check install migrate migration seed check-embeds worker scheduler ingest enrich check-links poll-feeds embed ab-report loadtest curate eval-curator exclude-sites image integration check test-db

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

# Take pages from the sites in backend/app/ingestion/excluded_sites.txt out of Hop
exclude-sites:
	cd backend && uv run python -m scripts.exclude_sites

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

# The API as a container image (backend/Dockerfile)
image:
	docker build -t hop-api backend

# Build and start the API container next to the services, prepare its own
# database (hop_it), then run the end-to-end tests in backend/integration/
integration:
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -tc "SELECT 1 FROM pg_database WHERE datname = '\''hop_it'\''" | grep -q 1 || createdb -U "$$POSTGRES_USER" hop_it'
	docker compose exec redis redis-cli -n 14 FLUSHDB
	docker compose --profile app up -d --build --wait api
	docker compose exec api alembic upgrade head
	docker compose exec api python -m scripts.seed_pages
	cd backend && API_URL=http://127.0.0.1:8001 MAILPIT_URL=http://127.0.0.1:8025 uv run pytest integration -v
	docker compose --profile app stop api

test-db:
	docker compose exec db sh -c 'createdb -U "$$POSTGRES_USER" hop_test'