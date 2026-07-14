.PHONY: test dashboard-dev dashboard-build dashboard-test dashboard-browser-test lint links

test:
	pytest tests/ -q

lint:
	ruff check retrieval_observatory tests scripts

links:
	python scripts/check_markdown_links.py

dashboard-dev:
	npm --prefix retrieval_observatory/dashboard/ui install
	npm --prefix retrieval_observatory/dashboard/ui run dev

dashboard-build:
	npm --prefix retrieval_observatory/dashboard/ui run build

dashboard-test:
	npm --prefix retrieval_observatory/dashboard/ui run test

dashboard-browser-test:
	pytest tests/browser -v --tb=short
