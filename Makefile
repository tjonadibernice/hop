.PHONY: up down api web lint test build format check

up:
	docker compose up -d

down:
	docker compose down

api:
	cd backend && uv run uvicorn app.main:app --reload

web:
	cd frontend && npm run dev

lint:
	cd backend && uv run ruff check .
	cd frontend && npm run lint

test:
	cd backend && uv run pytest

build:
	cd frontend && npm run build

format:
	cd backend && uv run ruff format .
	cd frontend && npm run format

check: lint test build
