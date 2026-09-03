.PHONY: install run sample test lint fmt eval clean

install:
	uv sync

run:
	uv run pipeline run --topic "AI agents for SMBs"

sample:
	uv run pipeline run --topic "AI agents for SMBs" --limit 15 --run-id sample_run

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

eval:
	uv run pipeline eval

clean:
	rm -rf .cache .pytest_cache .ruff_cache
