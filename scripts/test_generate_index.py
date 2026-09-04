"""Tests for generate_index.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

from generate_index import find_hygiene_violations, validate_plugin


def _plugin(files: dict[str, str | bytes]) -> Path:
    plugin_dir = Path(tempfile.mkdtemp(prefix="atk-registry-")) / "demo"
    for name, content in files.items():
        target = plugin_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
    return plugin_dir


def test_a_file_carrying_a_real_home_path_is_reported():
    # Given
    leaked = "/Users/jrutherford/.claude/projects"
    plugin_dir = _plugin({"server/lineage.py": f'ROOT = "{leaked}"\n'})

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert len(violations) == 1
    assert "server/lineage.py" in violations[0]
    assert leaked in violations[0]


def test_documentation_placeholders_are_not_reported():
    # Given
    plugin_dir = _plugin(
        {
            "README.md": "Point it at /Users/you/projects/myrepo\n",
            "SKILL.md": 'run("/Users/.../.atk/plugins/my-plugin")\n',
            "preview/test_preview.py": 'p = f"/Users/x/.claude/projects/{h}"\n',
        }
    )

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert violations == []


def test_placeholders_in_slug_form_are_not_reported():
    # Given
    plugin_dir = _plugin({"preview/test_preview.py": 'proj = "-Users-x--atk"\n'})

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert violations == []


def test_operator_only_paths_are_reported():
    # Given
    plugin_dir = _plugin(
        {
            "custom/docker-compose.override.yml": "services: {}\n",
            "custom/model-eval-runs/run.json": "{}\n",
        }
    )

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert len(violations) == 2
    assert all("operator-only path" in v for v in violations)


def test_an_ignored_env_file_is_not_reported():
    # Given
    plugin_dir = _plugin({".env": "TOKEN=abc\n", "README.md": "docs\n"})

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert violations == []


def test_a_binary_file_is_skipped_rather_than_decoded():
    # Given
    plugin_dir = _plugin(
        {
            "assets/icon.png": b"\x89PNG\r\n\x1a\n\xcf\xfe",
            "README.md": "See /Users/jrutherford/notes\n",
        }
    )

    # When
    violations = find_hygiene_violations(plugin_dir)

    # Then
    assert len(violations) == 1
    assert "README.md" in violations[0]


def test_validation_rejects_a_plugin_with_hygiene_violations():
    # Given
    plugin_dir = _plugin({"custom/notes.md": "local only\n"})

    # When
    result = validate_plugin(plugin_dir)

    # Then
    assert isinstance(result, str)
    assert "custom/notes.md" in result
