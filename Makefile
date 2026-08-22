.PHONY: lint test test-cov validate refresh clean install dev

PYTHON ?= python3
RUFF ?= ruff
MYPY ?= mypy
PYTEST ?= pytest

lint:
	$(RUFF) format --check
	$(RUFF) check
	$(MYPY)

test:
	$(PYTEST) -m "not slow" --no-cov

test-cov:
	$(PYTEST) -m "not slow"

validate:
	find . -name "*.xml" -not -path "./.git/*" -exec xmllint --noout {} +
	lint-imports

refresh:
	scripts/refresh-screenshot-db.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov build dist

install:
	pip install -e .

dev:
	pip install -e ".[dev]"
	pre-commit install