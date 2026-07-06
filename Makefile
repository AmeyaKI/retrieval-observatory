.PHONY: test dashboard-dev dashboard-build lint

test:
	pytest tests/ -q

lint:
	python -m compileall retrieval_observatory -q

dashboard-dev:
	npm --prefix retrieval_observatory/dashboard/ui install
	npm --prefix retrieval_observatory/dashboard/ui run dev

dashboard-build:
	npm --prefix retrieval_observatory/dashboard/ui install
	npm --prefix retrieval_observatory/dashboard/ui run build

dashboard-test:
	npm --prefix retrieval_observatory/dashboard/ui run test
