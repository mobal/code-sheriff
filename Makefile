all: bandit format lint ty test

bandit:
	uv run -m bandit --severity-level high --confidence-level high -r app/ -vvv

format:
	uv run ruff format .

install:
	uv sync

lint:
	uv run ruff check app/ tests/ --fix --statistics

test:
	uv run pytest tests/ --cov=app --cov-report=term-missing --cov-branch

ty:
	uv run ty check