.PHONY: help venv install run dev test demo clean

IMAGE  := novellia-api
PORT   := 8000
# The project needs >= 3.11; `python3` on this machine is 3.8, so pick the
# newest available rather than whatever happens to be first on PATH.
SYSPY  := $(shell command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
PY     := .venv/bin/python
PIP    := .venv/bin/pip

help:
	@echo "make run     Build and run in Docker on :$(PORT)  (no local Python needed)"
	@echo "make dev     Run locally with autoreload"
	@echo "make test    Run the test suite locally"
	@echo "make demo    Curl every endpoint, including the messy records"
	@echo "make clean   Remove the venv, the SQLite file, and caches"

venv:
	@test -d .venv || $(SYSPY) -m venv .venv
	@$(PIP) install --quiet --upgrade pip

install: venv
	@$(PIP) install --quiet -e ".[dev]"

run:
	docker build -t $(IMAGE) .
	docker run --rm -p $(PORT):8000 $(IMAGE)

dev: install
	.venv/bin/uvicorn app.main:app --reload --port $(PORT)

test: install
	.venv/bin/pytest -q

demo:
	./demo.sh

clean:
	rm -rf .venv *.db .pytest_cache **/__pycache__ *.egg-info
