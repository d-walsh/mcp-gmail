.PHONY: install test lint format run

install:
	uv sync

test:
	timeout 30 uv run pytest tests/ -v

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

run:
	uv run mcp dev mcp_gmail/server.py
