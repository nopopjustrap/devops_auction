PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
-include .env
export APP_NAME DATABASE_PATH SESSION_TTL_HOURS COOKIE_SECURE
BACKUP_FILE ?=
RESTORE_REPLACE ?= 0
APP_STOPPED ?= 0

.PHONY: setup run migrate backup restore quality security test verify migration-check backup-check mutation-check clean
setup:
	PYTHON="$(PYTHON)" sh scripts/setup.sh
run:
	$(VENV)/bin/uvicorn app.main:app --reload
migrate:
	$(VENV_PYTHON) -m app.migrate
backup:
	$(VENV_PYTHON) -m app.backup backup $(if $(BACKUP_FILE),--file "$(BACKUP_FILE)")
restore:
	$(VENV_PYTHON) -m app.backup restore --file "$(BACKUP_FILE)" $(if $(filter 1,$(RESTORE_REPLACE)),--replace) $(if $(filter 1,$(APP_STOPPED)),--app-stopped)
quality:
	$(VENV)/bin/ruff check app tests migrations scripts
	$(VENV)/bin/ruff format --check app tests migrations scripts
security:
	mkdir -p reports
	$(VENV)/bin/bandit -r app migrations -f json -o reports/bandit.json
# Full suite includes migrations and backup/restore, with an 85% branch-aware gate.
test:
	mkdir -p reports
	$(VENV_PYTHON) -m pytest --functional-coverage --cov=app --cov-branch --cov-report=term-missing --cov-report=xml:reports/coverage.xml --cov-report=html:reports/htmlcov --cov-fail-under=85 --junitxml=reports/junit.xml
migration-check:
	$(VENV_PYTHON) -m pytest tests/test_migrations.py
backup-check:
	$(VENV_PYTHON) -m pytest tests/test_backup.py
mutation-check:
	$(VENV_PYTHON) scripts/mutation_check.py
# Recipes are explicitly sequential, including when the caller uses make -j.
verify:
	$(VENV_PYTHON) -m pip check
	$(MAKE) quality
	$(MAKE) security
	$(MAKE) test
	$(MAKE) mutation-check
clean:
	$(VENV_PYTHON) -c "from pathlib import Path; import shutil; shutil.rmtree('reports', ignore_errors=True); Path('.coverage').unlink(missing_ok=True)"

.PHONY: backup-demo
backup-demo:
	$(VENV_PYTHON) scripts/backup_demo.py
