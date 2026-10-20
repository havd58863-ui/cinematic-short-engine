PYTHON ?= python3
VENV ?= .venv
UV_CACHE_DIR ?= .cache/uv

.PHONY: setup test lint doctor validate fetch-openmontage locks

setup:
	uv venv $(VENV) --python 3.12
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv pip install --python $(VENV)/bin/python -r requirements/locks/dev.txt

test:
	PYTHONPATH=src $(VENV)/bin/python -m pytest -q

lint:
	$(VENV)/bin/ruff check src tests scripts

doctor:
	PYTHONPATH=src $(VENV)/bin/python -m engine.cli doctor --json

validate:
	PYTHONPATH=src $(VENV)/bin/python -m engine.cli validate-config --json
	PYTHONPATH=src $(VENV)/bin/python -m engine.cli validate-toolchain --json

fetch-openmontage:
	$(PYTHON) scripts/fetch_openmontage.py

locks:
	uv pip compile pyproject.toml --extra providers --extra research --extra writing --extra bot --extra subtitles --python-version 3.12 --output-file requirements/locks/core.txt
	uv pip compile pyproject.toml --extra providers --extra research --extra writing --extra bot --extra subtitles --extra dev --python-version 3.12 --output-file requirements/locks/dev.txt
	uv pip compile pyproject.toml --extra media --extra audio --extra subtitles --python-version 3.12 --output-file requirements/locks/media.txt
	uv pip compile pyproject.toml --extra ml --python-version 3.12 --extra-index-url https://download.pytorch.org/whl/cpu --emit-index-url --output-file requirements/locks/ml.txt
	uv pip compile pyproject.toml --extra align --python-version 3.12 --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match --emit-index-url --output-file requirements/locks/align.txt
	uv pip compile pyproject.toml --extra voice-fallback --python-version 3.12 --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match --emit-index-url --output-file requirements/locks/voice-fallback.txt
