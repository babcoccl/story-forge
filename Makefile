.PHONY: install install-dev migrate upgrade downgrade run run-dev lint format test db-bootstrap

VENV=.venv
PYTHON=$(VENV)/bin/python
PIP=$(VENV)/bin/pip
ALEMBIC=$(VENV)/bin/alembic
UVICORN=$(VENV)/bin/uvicorn

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

db-bootstrap:
	sudo -u postgres psql -f infra/postgres_bootstrap.sql

migrate:
	cd backend && $(ALEMBIC) revision --autogenerate -m "$(msg)"

upgrade:
	cd backend && $(ALEMBIC) upgrade head

downgrade:
	cd backend && $(ALEMBIC) downgrade -1

run:
	$(UVICORN) backend.app.main:app --host 0.0.0.0 --port 8000

run-dev:
	$(UVICORN) backend.app.main:app --host 0.0.0.0 --port 8000 --reload

lint:
	$(VENV)/bin/ruff check backend/

format:
	$(VENV)/bin/black backend/

test:
	$(VENV)/bin/pytest backend/tests/ -v