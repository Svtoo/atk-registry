.PHONY: validate generate sync check

# Validate all plugins without writing index
validate:
	uv run python scripts/generate_index.py --check

# Generate index.yaml
generate:
	uv run python scripts/generate_index.py

# Sync dependencies
sync:
	uv sync

# Lint and format check
check:
	uv run ruff check scripts
	uv run ruff format --check scripts

