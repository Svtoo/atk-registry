"""Runtime settings: one declaration per knob, one place to read it.

SCHEMA is also the allowlist: the settings API only exposes and accepts names
declared here. Changes apply in memory at once and are written back to the
plugin's .env so they survive a restart.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "sonnet"
DEFAULT_REGEN_TIMEOUT = 180.0


@dataclass(frozen=True)
class Setting:
    name: str
    kind: str                      # "float" | "str"
    default: object
    label: str
    help: str
    runtime: bool = False          # can change without a restart
    minimum: "float | None" = None
    maximum: "float | None" = None
    choices: "tuple | None" = None


SCHEMA: "tuple[Setting, ...]" = (
    Setting(
        "CCD_REGEN_TIMEOUT", "float", DEFAULT_REGEN_TIMEOUT,
        "Rebuild time limit",
        "How long to let a dashboard rebuild run before stopping it. "
        "Large chats need more; most rebuilds finish well under 180 seconds.",
        runtime=True, minimum=30, maximum=900,
    ),
    Setting(
        "CCD_MODEL", "str", DEFAULT_MODEL,
        "Model",
        "Which model rebuilds the dashboard, for example sonnet or haiku.",
        runtime=True,
    ),
    Setting(
        "CCD_LOG_LEVEL", "str", "INFO",
        "Log detail",
        "DEBUG also records the full prompt sent for every rebuild, which makes "
        "the log much larger.",
        runtime=True, choices=("INFO", "DEBUG"),
    ),
)

_BY_NAME = {s.name: s for s in SCHEMA}


def _coerce(setting: Setting, raw) -> object:
    """Text (or an already-typed value) to the setting's type, or ValueError with
    a message meant for a person."""
    if setting.kind == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{setting.label} must be a number.")
        if setting.minimum is not None and value < setting.minimum:
            raise ValueError(f"{setting.label} must be at least {setting.minimum:g}.")
        if setting.maximum is not None and value > setting.maximum:
            raise ValueError(f"{setting.label} must be at most {setting.maximum:g}.")
        return value
    text = str(raw).strip()
    if not text:
        raise ValueError(f"{setting.label} cannot be empty.")
    if setting.choices and text.upper() not in {c.upper() for c in setting.choices}:
        raise ValueError(f"{setting.label} must be one of: {', '.join(setting.choices)}.")
    if setting.choices:
        text = text.upper()
    return text


def _format(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class Settings:
    """Live values for every declared setting, backed by a .env file."""

    def __init__(self, env_path: "Path | str", environ: "dict | None" = None):
        self._env_path = Path(env_path)
        self._lock = threading.Lock()
        source = os.environ if environ is None else environ
        self._values: dict = {}
        for setting in SCHEMA:
            raw = source.get(setting.name)
            if raw is None or str(raw).strip() == "":
                self._values[setting.name] = setting.default
                continue
            try:
                self._values[setting.name] = _coerce(setting, raw)
            except ValueError:
                # A bad value in the environment must not stop the server.
                self._values[setting.name] = setting.default

    def get(self, name: str):
        return self._values[name]

    def public(self) -> "list[dict]":
        """Every declared setting with its value and what it means."""
        out = []
        for setting in SCHEMA:
            out.append({
                "name": setting.name,
                "label": setting.label,
                "help": setting.help,
                "kind": setting.kind,
                "value": self._values[setting.name],
                "default": setting.default,
                "runtime": setting.runtime,
                "minimum": setting.minimum,
                "maximum": setting.maximum,
                "choices": list(setting.choices) if setting.choices else None,
            })
        return out

    def update(self, name: str, raw) -> dict:
        """Validate, apply in memory, and persist to .env. Raises ValueError with
        a readable message if the name is not declared or the value is invalid."""
        setting = _BY_NAME.get(name)
        if setting is None:
            raise ValueError("That is not a setting you can change.")
        value = _coerce(setting, raw)
        with self._lock:
            self._values[name] = value
            self._persist(name, _format(value))
        return {"name": name, "value": value, "applies_now": setting.runtime}

    def _persist(self, name: str, text: str) -> None:
        """Rewrite just this key in .env, leaving every other line, comment and
        blank line exactly as it was. Written via a temp file so a crash midway
        cannot leave the user with a truncated config."""
        quoted = f'"{text}"' if (text == "" or any(c in text for c in ' \t#"\'')) else text
        line = f"{name}={quoted}"
        lines: "list[str]" = []
        if self._env_path.is_file():
            lines = self._env_path.read_text(encoding="utf-8").splitlines()
        for i, existing in enumerate(lines):
            stripped = existing.lstrip()
            key = stripped[len("export "):] if stripped.startswith("export ") else stripped
            if key.split("=", 1)[0].strip() == name:
                lines[i] = line
                break
        else:
            lines.append(line)
        self._env_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._env_path.with_suffix(self._env_path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self._env_path)
