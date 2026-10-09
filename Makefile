PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
RUFF   := .venv/bin/ruff
MYPY   := .venv/bin/mypy
PYTEST := .venv/bin/pytest
PIP_AUDIT := .venv/bin/pip-audit

.PHONY: setup lint typecheck test audit check clean

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt
	$(PIP) install -e .

lint:
	$(RUFF) format --check src tests
	$(RUFF) check src tests

typecheck:
	$(MYPY) src

test:
	$(PYTEST) --cov=k8s_toolkit --cov-fail-under=80

audit:
	$(PIP_AUDIT) -r requirements-dev.txt --desc

check: lint typecheck test audit

clean:
	rm -rf .venv build dist *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache .coverage
