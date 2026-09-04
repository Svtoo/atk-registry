.PHONY: validate generate sync check test hooks

# Validate all plugins without writing index
validate:
	uv run python scripts/generate_index.py --check

# Generate index.yaml
generate:
	uv run python scripts/generate_index.py

# Sync dependencies
sync:
	uv sync

# Install the repo's git hooks
hooks:
	git config core.hooksPath .githooks

# Run script tests
test:
	uv run pytest scripts -q

# Lint and format check
check:
	uv run ruff check scripts
	uv run ruff format --check scripts

