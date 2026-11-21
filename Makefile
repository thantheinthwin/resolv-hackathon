PYTHON ?= python3.12
VENV := .venv/bin/python

.PHONY: setup dev check score

setup:
	@command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || { echo "Install FFmpeg (including ffprobe) before setup." >&2; exit 1; }
	$(PYTHON) -m venv .venv
	$(VENV) -m pip install -r requirements-dev.txt
	npm --prefix web ci

dev:
	bash scripts/dev.sh

check:
	$(VENV) -m ruff check .
	$(VENV) -m ruff format --check .
	$(VENV) -m pytest -ra
	npm --prefix web run lint
	npm --prefix web run format:check
	npm --prefix web run typecheck

score:
	@test -f judge/score.py || { echo "The judge scoring tool (judge/score.py) is not implemented yet." >&2; exit 1; }
	$(VENV) -m judge.score
