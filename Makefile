.PHONY: all build build-layer build-lambda \
		upload upload-lambda upload-layer \
		format install lint bandit test tflint ty

all: build bandit format lint ty test

build: build-layer build-lambda

build-layer:
	./scripts/build_requirements_layer.sh

build-lambda:
	./scripts/build_api.sh

upload: upload-layer upload-lambda

upload-lambda:
	./scripts/upload_api.sh

upload-layer:
	./scripts/upload_requirements_layer.sh

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
