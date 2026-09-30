# Ehnglish — common commands. Ports are registered in /home/user/Projects/PORTS.md.
NODE_BIN := $(HOME)/.nvm/versions/node/v24.16.0/bin
export PATH := $(NODE_BIN):$(PATH)

.PHONY: help setup db-test db-test-down test test-server test-web e2e dev-api dev-web dev-worker build lint fixture up down logs

help:
	@grep -E '^[a-z-]+:.*#' Makefile | sed 's/:.*#/ —/'

setup:            # install server (uv) and web (npm) dependencies
	cd server && uv sync
	cd web && npm ci && npx playwright install chromium

db-test:          # start the throwaway Postgres on 127.0.0.1:3607
	docker compose -f deploy/docker-compose.test.yml up -d --wait

db-test-down:
	docker compose -f deploy/docker-compose.test.yml down

test-server: db-test   # pytest
	cd server && uv run pytest -q

test-web:         # vitest
	cd web && npm test

test: test-server test-web   # all unit/integration tests

fixture:          # regenerate the fake-mic WAV for Playwright
	cd server && uv run python scripts/make_fixture_wav.py

e2e: db-test fixture   # Playwright smoke test (starts API + Vite itself)
	cd web && npx playwright test

lint:
	cd server && uv run ruff check . && uv run python ../content/lint.py
	cd web && npm run typecheck && npm run lint

dev-api: db-test  # API on 127.0.0.1:3305 with the dev identity
	cd server && EHNGLISH_ENV=dev EHNGLISH_DEV_EMAIL=dev@example.com uv run alembic upgrade head && \
	  EHNGLISH_ENV=dev EHNGLISH_DEV_EMAIL=dev@example.com uv run uvicorn app.main:app --host 127.0.0.1 --port 3305 --reload

dev-worker:
	cd server && EHNGLISH_ENV=dev uv run python -m app.worker

dev-web:          # Vite on 127.0.0.1:3914 (proxies /api -> 3305)
	cd web && npm run dev

build:            # production image
	docker compose -f deploy/docker-compose.yml build

up:               # production stack on this PC (needs deploy/.env)
	docker compose -f deploy/docker-compose.yml up -d --build

down:
	docker compose -f deploy/docker-compose.yml down

logs:
	docker compose -f deploy/docker-compose.yml logs -f --tail=100
