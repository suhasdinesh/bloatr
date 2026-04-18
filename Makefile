.PHONY: install test run build publish clean

install:
	pip install -e ".[dev]" 2>/dev/null || pip install -e . && pip install pytest pytest-cov

test:
	pytest tests/ -v --cov=bloatr --cov-report=term-missing

run:
	python -m bloatr

build:
	python -m build

publish:
	python -m twine upload dist/*

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache __pycache__
