PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

-include .env
export APP_NAME
export DATABASE_PATH
export SESSION_TTL_HOURS
export COOKIE_SECURE

.PHONY: setup migrate run test quality verify clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements-dev.txt

migrate:
	$(VENV_PYTHON) -m app.migrate

run:
	$(VENV)/bin/uvicorn app.main:app --reload

test:
	$(VENV_PYTHON) -m pytest -q

quality:
	$(VENV)/bin/ruff check app tests
	$(VENV)/bin/ruff format --check app tests

verify: quality test

clean:
	$(PYTHON) -c "from pathlib import Path; p=Path('data/auctions.db'); p.unlink(missing_ok=True)"
