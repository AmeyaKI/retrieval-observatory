.PHONY: test dashboard-dev dashboard-build dashboard-test dashboard-browser-test lint links contracts release-build release-smoke release-external

test:
	pytest tests/ -q

lint:
	ruff check retrieval_observatory tests scripts

links:
	python scripts/check_markdown_links.py

contracts:
	python scripts/check_public_surface.py
	python scripts/check_public_vocabulary.py
	python scripts/check_markdown_links.py
	pytest tests/contracts -q

release-build: dashboard-build
	python -m build
	twine check dist/*

release-smoke: release-build
	python scripts/smoke_external_project.py --wheel dist/retrieval_observatory-*.whl --fixture all --artifacts artifacts/external-fixtures

release-external:
	python scripts/smoke_external_project.py --wheel $(WHEEL) --fixture all --artifacts artifacts/external-fixtures

dashboard-dev:
	npm --prefix retrieval_observatory/dashboard/ui install
	npm --prefix retrieval_observatory/dashboard/ui run dev

dashboard-build:
	npm --prefix retrieval_observatory/dashboard/ui run build

dashboard-test:
	npm --prefix retrieval_observatory/dashboard/ui run test

dashboard-browser-test:
	pytest tests/browser -v --tb=short
