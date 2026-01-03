.PHONY: all build build-layer build-api format install lint bandit test tflint ty install

all: build bandit format lint ty test

build: build-layer build-api

build-layer:
	./scripts/build_requirements_layer.sh

build-api:
	./scripts/build_api.sh

format:
	uv run ruff format .

install:
	uv sync

lint:
	uv run ruff check app/ tests/ --fix

bandit:
	uv run -m bandit --severity-level high --confidence-level high -r app/ -vvv

test:
	uv run pytest tests/ --cov=app --cov-report=term-missing --cov-branch

tflint:
	tflint --init
	tflint --chdir=infrastructure/

ty:
	uv run ty check
