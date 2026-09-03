.PHONY: install run sample test lint fmt eval pack clean

install:
	uv sync

run:
	uv run pipeline run --topic "AI agents for SMBs"

sample:
	uv run pipeline run --topic "AI agents for SMBs" --limit 15 --run-id sample-run

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

pack:
	npx --yes repomix@latest .

clean:
	rm -rf .cache .pytest_cache .ruff_cache
