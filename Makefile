.PHONY: install check test lint format typecheck up down migrate benchmark

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy

test:
	pytest --cov=gateway --cov-report=term-missing

check: lint typecheck test

up:
	docker compose up --build

down:
	docker compose down

migrate:
	alembic upgrade head

benchmark:
	gateway-benchmark --jobs 10000 --concurrency 200
