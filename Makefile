# Part of the ifURI solution.
PY ?= python3

.PHONY: test install smoke single-source build check
SINGLE_SOURCE_ROOTS ?= .

install: ## editable install with connector + test extras
	$(PY) -m pip install -e ".[connector,test,dev]"

test: ## pytest (routing logic + contract conformance)
	$(PY) -m pytest tests/ -q

smoke: ## import + router:// bindings smoke after install
	$(PY) -c "from urirun_connector_router import urirun_bindings; b=urirun_bindings()['bindings']; assert 'router://host/plan/query/diagnose' in b, b; print('router bindings ok')"

single-source: ## routing kernel defined once; old paths must be shims
	$(PY) -m urirun_connector_router.check_single_source $(SINGLE_SOURCE_ROOTS)

build: ## sdist + wheel + twine metadata check
	$(PY) -m build && $(PY) -m twine check dist/*

check: install test smoke single-source build ## install-smoke + tests + publish-readiness
