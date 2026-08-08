.PHONY: install dev test lint format typecheck migrate topics smoke docker-build demo

install:
	pip install -e ".[dev]"

dev:
	uvicorn scam2market.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest

lint:
	ruff check src tests scripts alembic

format:
	ruff format src tests scripts alembic

typecheck:
	mypy src tests

migrate:
	alembic upgrade head

topics:
	python scripts/create_topics.py

smoke:
	python scripts/publish_test_event.py

docker-build:
	docker compose build

demo:
	docker compose --profile demo up replay-scheduler
