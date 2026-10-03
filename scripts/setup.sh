#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Use Python 3.12"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
.venv/bin/python -m pip check
if [ ! -e .env ]; then
    cp .env.example .env
    chmod 600 .env
fi
printf '%s\n' 'Setup complete. For an existing database: make backup, then make migrate.'
