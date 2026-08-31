"""Tests for runtime settings (config.py): coercion, bounds, the schema as an
allowlist, and .env persistence that leaves the rest of the file alone.
Run: ../.venv/bin/python test_config.py
"""

import tempfile
from pathlib import Path

from config import SCHEMA, Setting, Settings
from testutil import run_module_tests

_SECRET = Setting("CCD_TEST_TOKEN", "str", "", "Test token",
                  "Write-only token for the secret tests.",
                  runtime=True, secret=True)


def _settings(env_text=None, environ=None, schema=SCHEMA):
    d = Path(tempfile.mkdtemp())
    env_path = d / ".env"
    if env_text is not None:
        env_path.write_text(env_text, encoding="utf-8")
    return Settings(env_path, environ=environ or {}, schema=schema), env_path


# ─── loading ───────────────────────────────────────────────────────────

def test_missing_environment_uses_declared_defaults():
    s, _ = _settings()
    assert s.get("CCD_REGEN_TIMEOUT") == 180.0
    assert s.get("CCD_MODEL") == "sonnet"
    assert s.get("CCD_LOG_LEVEL") == "INFO"
    assert s.get("CCD_PREVIEW_PANE") is True
    assert s.get("CCD_JOURNEY") is False, "journey is opt-in"


def test_a_bool_setting_reads_common_spellings():
    for raw, expected in (("false", False), ("off", False), ("0", False),
                          ("true", True), ("YES", True), ("1", True)):
        s, _ = _settings(environ={"CCD_PREVIEW_PANE": raw})
        assert s.get("CCD_PREVIEW_PANE") is expected, f"{raw!r} must read as {expected}"


def test_environment_values_are_read_and_typed():
    configured_timeout = "240"
    s, _ = _settings(environ={"CCD_REGEN_TIMEOUT": configured_timeout, "CCD_MODEL": "haiku"})
    assert s.get("CCD_REGEN_TIMEOUT") == 240.0, "a numeric setting must come back as a number"
    assert s.get("CCD_MODEL") == "haiku"


def test_an_unusable_environment_value_falls_back_instead_of_crashing():
    s, _ = _settings(environ={"CCD_REGEN_TIMEOUT": "not-a-number"})
    assert s.get("CCD_REGEN_TIMEOUT") == 180.0, "a bad env value must not stop the server"


def test_blank_environment_value_uses_the_default():
    s, _ = _settings(environ={"CCD_MODEL": "   "})
    assert s.get("CCD_MODEL") == "sonnet"


# ─── validation, the schema as allowlist ───────────────────────────────

def test_update_rejects_a_name_not_in_the_schema():
    s, _ = _settings()
    try:
        s.update("PATH", "/tmp")
        assert False, "an undeclared key must be refused"
    except ValueError as e:
        assert "not a setting" in str(e), e


def test_update_enforces_the_declared_range():
    s, _ = _settings()
    too_small = 5
    try:
        s.update("CCD_REGEN_TIMEOUT", too_small)
        assert False, "a value below the minimum must be refused"
    except ValueError as e:
        assert "at least 30" in str(e), e


def test_update_enforces_declared_choices():
    s, _ = _settings()
    try:
        s.update("CCD_LOG_LEVEL", "CHATTY")
        assert False, "a value outside the choices must be refused"
    except ValueError as e:
        assert "INFO" in str(e) and "DEBUG" in str(e), e


def test_a_choice_is_accepted_case_insensitively():
    s, _ = _settings()
    s.update("CCD_LOG_LEVEL", "debug")
    assert s.get("CCD_LOG_LEVEL") == "DEBUG"


def test_update_rejects_a_value_that_is_not_a_bool():
    s, _ = _settings()
    try:
        s.update("CCD_PREVIEW_PANE", "maybe")
        assert False, "a non-boolean value must be refused"
    except ValueError as e:
        assert "on or off" in str(e), e


# ─── applying + persisting ─────────────────────────────────────────────

def test_update_applies_in_memory_immediately():
    s, _ = _settings()
    new_timeout = 300
    result = s.update("CCD_REGEN_TIMEOUT", new_timeout)
    assert s.get("CCD_REGEN_TIMEOUT") == 300.0, "the running server must see the new value at once"
    assert result["applies_now"] is True, "a runtime setting needs no restart"


def test_persist_rewrites_only_its_own_key():
    original = (
        "# managed by atk\n"
        "CCD_MODEL=sonnet\n"
        "CCD_REGEN_TIMEOUT=180\n"
        "\n"
        "# keep me\n"
        "SOMETHING_ELSE=untouched\n"
    )
    s, env_path = _settings(env_text=original)
    s.update("CCD_REGEN_TIMEOUT", 240)
    written = env_path.read_text(encoding="utf-8")
    assert "CCD_REGEN_TIMEOUT=240" in written
    assert "CCD_MODEL=sonnet" in written, "an unrelated key must survive"
    assert "SOMETHING_ELSE=untouched" in written, "an unrelated key must survive"
    assert "# managed by atk" in written and "# keep me" in written, "comments must survive"
    assert written.count("CCD_REGEN_TIMEOUT=") == 1, "the key must be replaced, not duplicated"


def test_persist_appends_a_key_that_was_not_in_the_file():
    s, env_path = _settings(env_text="CCD_MODEL=sonnet\n")
    s.update("CCD_LOG_LEVEL", "DEBUG")
    written = env_path.read_text(encoding="utf-8")
    assert "CCD_LOG_LEVEL=DEBUG" in written
    assert "CCD_MODEL=sonnet" in written


def test_persist_handles_an_export_prefixed_line():
    s, env_path = _settings(env_text="export CCD_MODEL=sonnet\n")
    s.update("CCD_MODEL", "haiku")
    written = env_path.read_text(encoding="utf-8")
    assert "CCD_MODEL=haiku" in written
    assert written.count("CCD_MODEL") == 1, "the exported key must be replaced, not duplicated"


def test_a_whole_number_timeout_is_written_without_a_decimal_point():
    s, env_path = _settings()
    s.update("CCD_REGEN_TIMEOUT", 240)
    assert "CCD_REGEN_TIMEOUT=240\n" in env_path.read_text(encoding="utf-8")


def test_a_bool_is_written_in_the_spelling_the_hook_reads():
    s, env_path = _settings()
    result = s.update("CCD_PREVIEW_PANE", "false")
    assert s.get("CCD_PREVIEW_PANE") is False
    assert result["applies_now"] is True
    assert "CCD_PREVIEW_PANE=false\n" in env_path.read_text(encoding="utf-8")
    s.update("CCD_PREVIEW_PANE", "true")
    assert "CCD_PREVIEW_PANE=true\n" in env_path.read_text(encoding="utf-8")


# ─── what a client may see ─────────────────────────────────────────────

def test_public_describes_each_setting_for_a_settings_page():
    s, _ = _settings()
    by_name = {item["name"]: item for item in s.public()}
    timeout = by_name["CCD_REGEN_TIMEOUT"]
    assert timeout["label"] and timeout["help"], "a setting must explain itself"
    assert timeout["minimum"] == 30 and timeout["maximum"] == 900
    assert by_name["CCD_LOG_LEVEL"]["choices"] == ["INFO", "DEBUG"]
    pane = by_name["CCD_PREVIEW_PANE"]
    assert pane["kind"] == "bool" and pane["value"] is True
    assert pane["secret"] is False


def test_every_declared_setting_reaches_the_settings_page():
    import config
    s, _ = _settings()
    assert {i["name"] for i in s.public()} == {d.name for d in config.SCHEMA}


def test_a_secret_value_never_appears_in_the_public_view():
    s, _ = _settings(environ={"CCD_TEST_TOKEN": "hunter2"}, schema=SCHEMA + (_SECRET,))
    item = {i["name"]: i for i in s.public()}["CCD_TEST_TOKEN"]
    assert item["secret"] is True and item["set"] is True
    assert item["value"] is None and item["default"] is None
    assert "hunter2" not in repr(s.public())


def test_an_unset_secret_reports_it_has_no_value():
    s, _ = _settings(schema=SCHEMA + (_SECRET,))
    item = {i["name"]: i for i in s.public()}["CCD_TEST_TOKEN"]
    assert item["set"] is False


def test_updating_a_secret_marks_the_result_secret():
    s, env_path = _settings(schema=SCHEMA + (_SECRET,))
    result = s.update("CCD_TEST_TOKEN", "hunter2")
    assert result["secret"] is True
    assert "CCD_TEST_TOKEN=hunter2" in env_path.read_text(encoding="utf-8")


def test_a_plain_setting_update_is_not_marked_secret():
    s, _ = _settings()
    assert s.update("CCD_MODEL", "haiku")["secret"] is False


if __name__ == "__main__":
    run_module_tests(globals())
