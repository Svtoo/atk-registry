#!/usr/bin/env python3
"""Generate index.yaml from plugin directories.

This script:
1. Walks the plugins/ directory
2. Validates each plugin.yaml using ATK's schema
3. Generates index.yaml with plugin metadata
4. Exits non-zero if any validation fails

Usage:
    python scripts/generate_index.py [--check]

Options:
    --check     Validate only, don't write index.yaml (for CI validation step)
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from atk.manifest_schema import SourceType
from atk.plugin import load_plugin_schema
from atk.registry_schema import RegistryIndexSchema, RegistryPluginEntry
from atk.source import resolve_source

REGISTRY_ROOT = Path(__file__).parent.parent
PLUGINS_DIR = REGISTRY_ROOT / "plugins"
INDEX_FILE = REGISTRY_ROOT / "index.yaml"


def discover_plugins() -> list[Path]:
    """Find all plugin directories under plugins/."""
    if not PLUGINS_DIR.exists():
        return []

    return sorted(d for d in PLUGINS_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))


def validate_plugin(plugin_dir: Path) -> RegistryPluginEntry | str:
    """Validate a plugin and extract its info.

    Returns:
        RegistryPluginEntry on success, error message string on failure.
    """
    name = plugin_dir.name

    resolved = resolve_source(name)
    if resolved.source_type != SourceType.REGISTRY:
        return (
            f"Plugin name '{name}' resolves as {resolved.source_type.value} instead of registry. "
            f"Users running 'atk add {name}' would not reach the registry."
        )

    if not (plugin_dir / "README.md").exists():
        return "Missing README.md (required for all registry plugins)"

    try:
        schema = load_plugin_schema(plugin_dir)
        return RegistryPluginEntry(
            name=name,
            path=f"plugins/{name}",
            description=schema.description,
        )
    except (FileNotFoundError, ValueError) as e:
        return str(e)


def generate_index(plugins: list[RegistryPluginEntry]) -> RegistryIndexSchema:
    """Generate the index schema."""
    return RegistryIndexSchema(plugins=plugins)


def write_index(index: RegistryIndexSchema) -> None:
    """Write index to YAML file."""
    data = index.model_dump(mode="json")
    INDEX_FILE.write_text(yaml.dump(data, sort_keys=False, allow_unicode=True))


def main() -> int:
    """Main entry point."""
    check_only = "--check" in sys.argv

    plugin_dirs = discover_plugins()

    if not plugin_dirs:
        print("No plugins found in plugins/")
        # Empty registry is valid
        if not check_only:
            write_index(generate_index([]))
            print(f"Wrote empty {INDEX_FILE}")
        return 0

    # Validate all plugins
    valid_plugins: list[RegistryPluginEntry] = []
    errors: list[tuple[str, str]] = []

    for plugin_dir in plugin_dirs:
        result = validate_plugin(plugin_dir)
        if isinstance(result, RegistryPluginEntry):
            valid_plugins.append(result)
            print(f"✓ {plugin_dir.name}")
        else:
            errors.append((plugin_dir.name, result))
            print(f"✗ {plugin_dir.name}: {result}")

    # Report summary
    print()
    print(f"Valid: {len(valid_plugins)}, Invalid: {len(errors)}")

    if errors:
        print("\nValidation failed. Fix errors before merging.")
        return 1

    # Generate index
    if check_only:
        print("\nValidation passed (--check mode, index not written)")
    else:
        index = generate_index(valid_plugins)
        write_index(index)
        print(f"\nWrote {INDEX_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
