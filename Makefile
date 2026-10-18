# Changes to acceptance commands require independent CODEOWNER review.
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
	mkdir -p reports
	$(VENV_PYTHON) -m pytest tests/test_migrations.py --junitxml=reports/migrations.xml
backup-check:
	mkdir -p reports
	$(VENV_PYTHON) -m pytest tests/test_backup.py --junitxml=reports/backup.xml
mutation-check:
	$(VENV_PYTHON) scripts/mutation_check.py
# Recipes are explicitly sequential, including when the caller uses make -j.
verify:
	$(MAKE) policy-check
	$(VENV_PYTHON) -m pip check
	$(MAKE) quality
	$(MAKE) security
	$(MAKE) test
	$(MAKE) mutation-check
	$(MAKE) migration-check
	$(MAKE) backup-check
	$(MAKE) backup-demo
	$(MAKE) dependencies-check
	$(MAKE) secrets-check
	$(MAKE) container-build
	$(MAKE) container-check
	$(MAKE) container-scan
	$(MAKE) delivery-check
clean:
	$(VENV_PYTHON) -c "from pathlib import Path; import shutil; shutil.rmtree('reports', ignore_errors=True); Path('.coverage').unlink(missing_ok=True)"

.PHONY: backup-demo
backup-demo:
	$(VENV_PYTHON) scripts/backup_demo.py

# LR5: the CI jobs call these same targets. Docker is required for full verify.
include .ci/tools.env
export GITLEAKS_IMAGE TRIVY_IMAGE
IMAGE ?= auction-service:$(shell git rev-parse HEAD)
export IMAGE

.PHONY: dependencies-check secrets-check policy-check container-build container-check container-scan
.audit-venv/bin/pip-audit: requirements-audit.txt requirements-audit.lock
	$(VENV_PYTHON) -m venv .audit-venv
	.audit-venv/bin/python -m pip install -r requirements-audit.txt
dependencies-check: .audit-venv/bin/pip-audit
	mkdir -p reports
	.audit-venv/bin/pip-audit -r requirements.lock --disable-pip --no-deps --progress-spinner off --format json --output reports/dependencies.json
secrets-check:
	$(VENV_PYTHON) scripts/scan_secrets.py
policy-check:
	$(VENV_PYTHON) scripts/check_acceptance.py
container-build:
	docker build --pull --build-arg VCS_REF="$(shell git rev-parse HEAD)" --tag "$(IMAGE)" .
container-check:
	sh scripts/container_smoke.sh
container-scan:
	mkdir -p reports .cache/trivy
	docker run --rm --user "$$(id -u):$$(id -g)" --group-add "$$(stat -c %g /var/run/docker.sock)" -v /var/run/docker.sock:/var/run/docker.sock -v "$(CURDIR)/reports:/reports" -v "$(CURDIR)/.cache/trivy:/cache" "$(TRIVY_IMAGE)" image --cache-dir /cache --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output /reports/container-vulnerabilities.json "$(IMAGE)"

.PHONY: delivery-check
delivery-check:
	python3 scripts/delivery_demo.py
