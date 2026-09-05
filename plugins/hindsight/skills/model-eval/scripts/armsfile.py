#!/usr/bin/env python3
"""Single reader for arms.yaml.

PyYAML is not installed on this machine and the harness must not need a
virtualenv to run one shell script, so this parses the exact subset arms.yaml
uses, a top-level 'arms:' list of flat scalar mappings, and refuses anything
else. That refusal is the point: a silently half-parsed arm would run the wrong
model under the right label, and the results file would be a lie that nothing
downstream could detect.

    python3 armsfile.py --list
    python3 armsfile.py --validate
    python3 armsfile.py --export A        # shell assignments, for eval
    python3 armsfile.py --json dsv4pro
"""
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS_PATH = os.path.join(HERE, "arms.yaml")

# Every field is mandatory. An arm with a missing field is a configuration bug,
# not a request to fall back to a default: the default would be invisible in
# the results file and would quietly change what was measured.
FIELDS = {
    "id": str,
    "key": str,
    "provider": str,
    "model": str,
    "base_url": str,
    "strict_schema": bool,
    "max_concurrent": int,
    "note": str,
}

# Hindsight accepts letters, digits, dot, dash and underscore in a bank id.
# Restricted further here so a key cannot produce a bank name that differs from
# the key only in case, which Postgres identifiers would fold together.
KEY_RE = re.compile(r"^[a-z0-9_]+$")


class ArmsError(Exception):
    """Raised for any malformed arms.yaml. Always fatal to the caller."""


def _scalar(raw, where):
    """Parse one scalar value: quoted string, bool, int, or bare string."""
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        quote = raw[0]
        out = []
        i = 1
        while i < len(raw):
            char = raw[i]
            if char == "\\" and quote == '"' and i + 1 < len(raw):
                out.append(raw[i + 1])
                i += 2
                continue
            if char == quote:
                rest = raw[i + 1:].strip()
                # Only a comment may follow a closing quote. Trailing junk
                # usually means an unescaped quote inside the value, which
                # would otherwise truncate the string without complaint.
                if rest and not rest.startswith("#"):
                    raise ArmsError(f"{where}: unexpected text after closing quote: {rest!r}")
                return "".join(out)
            out.append(char)
            i += 1
        raise ArmsError(f"{where}: unterminated quoted string")
    # Unquoted: a ' #' begins a comment, a bare '#' at position 0 cannot occur
    # here because the line-splitter already handled empty values.
    cut = raw.find(" #")
    if cut != -1:
        raw = raw[:cut].strip()
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _split_key(line, where):
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
    if not match:
        raise ArmsError(f"{where}: expected 'key: value', got {line!r}")
    return match.group(1), match.group(2)


def parse(text, source="arms.yaml"):
    arms = []
    current = None
    in_arms = False
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        where = f"{source}:{lineno}"
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if indent == 0:
            if line != "arms:":
                raise ArmsError(f"{where}: the only top-level key is 'arms:', got {line!r}")
            if in_arms:
                raise ArmsError(f"{where}: 'arms:' appears twice")
            in_arms = True
            continue

        if not in_arms:
            raise ArmsError(f"{where}: content before 'arms:'")

        if line.startswith("- "):
            if indent != 2:
                raise ArmsError(f"{where}: list items must be indented 2 spaces, found {indent}")
            current = {}
            arms.append(current)
            key, value = _split_key(line[2:].strip(), where)
            current[key] = _scalar(value, where)
            continue

        if current is None:
            raise ArmsError(f"{where}: field outside any list item")
        if indent != 4:
            raise ArmsError(f"{where}: fields must be indented 4 spaces, found {indent}")
        key, value = _split_key(line, where)
        if key in current:
            raise ArmsError(f"{where}: duplicate field {key!r} in this arm")
        current[key] = _scalar(value, where)

    if not in_arms:
        raise ArmsError(f"{source}: no 'arms:' key")
    if not arms:
        raise ArmsError(f"{source}: 'arms:' is empty")
    _validate(arms, source)
    return arms


def _validate(arms, source):
    seen_ids, seen_keys = set(), set()
    for index, arm in enumerate(arms):
        label = f"{source}: arm #{index + 1} ({arm.get('key') or arm.get('id') or 'unnamed'})"
        missing = [f for f in FIELDS if f not in arm]
        if missing:
            raise ArmsError(f"{label}: missing field(s) {', '.join(sorted(missing))}")
        extra = [f for f in arm if f not in FIELDS]
        if extra:
            raise ArmsError(f"{label}: unknown field(s) {', '.join(sorted(extra))}")
        for field, want in FIELDS.items():
            value = arm[field]
            # bool is a subclass of int, so an int field would silently accept
            # 'true'. Check bool first and reject the cross-assignment.
            if want is bool and not isinstance(value, bool):
                raise ArmsError(f"{label}: {field} must be true or false, got {value!r}")
            if want is int and (isinstance(value, bool) or not isinstance(value, int)):
                raise ArmsError(f"{label}: {field} must be an integer, got {value!r}")
            if want is str and not isinstance(value, str):
                raise ArmsError(f"{label}: {field} must be a string, got {value!r}")
        if not KEY_RE.match(arm["key"]):
            raise ArmsError(f"{label}: key must match {KEY_RE.pattern}")
        for field in ("id", "provider", "model", "note"):
            if not arm[field].strip():
                raise ArmsError(f"{label}: {field} must not be empty")
        if arm["max_concurrent"] < 1:
            raise ArmsError(f"{label}: max_concurrent must be >= 1")
        if arm["id"] in seen_ids:
            raise ArmsError(f"{label}: duplicate id {arm['id']!r}")
        if arm["key"] in seen_keys:
            raise ArmsError(f"{label}: duplicate key {arm['key']!r}")
        seen_ids.add(arm["id"])
        seen_keys.add(arm["key"])


def load(path=ARMS_PATH):
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise ArmsError(f"cannot read {path}: {error}") from error
    return parse(text, source=os.path.basename(path))


def find(selector, path=ARMS_PATH):
    """Look an arm up by key or by id. Both are accepted so the letter used in
    write-ups and the slug used in filenames are interchangeable at the CLI."""
    arms = load(path)
    for arm in arms:
        if selector == arm["key"] or selector == arm["id"]:
            return arm
    known = ", ".join(f"{a['id']}/{a['key']}" for a in arms)
    raise ArmsError(f"unknown arm {selector!r}. Known arms: {known}")


def _export(arm):
    """Shell assignments for a caller to eval. Values are shell-quoted. No key
    is here: every arm runs on the key the dispatcher resolves from the
    environment, so a secret never passes through a printed line."""
    pairs = [
        ("ARM_ID", arm["id"]),
        ("ARM_KEY", arm["key"]),
        ("ARM_PROVIDER", arm["provider"]),
        ("ARM_MODEL", arm["model"]),
        ("ARM_BASE_URL", arm["base_url"]),
        ("ARM_STRICT_SCHEMA", "true" if arm["strict_schema"] else "false"),
        ("ARM_MAX_CONCURRENT", str(arm["max_concurrent"])),
    ]
    return "\n".join(f"{name}={shlex.quote(value)}" for name, value in pairs)


def main(argv):
    if len(argv) == 1 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    mode = argv[1]
    try:
        if mode == "--list":
            for arm in load():
                print(f"{arm['id']}  {arm['key']:<10} {arm['provider']:<11} "
                      f"{arm['model']:<26} strict={str(arm['strict_schema']).lower():<5}")
            return 0
        if mode == "--validate":
            arms = load()
            print(f"arms.yaml OK: {len(arms)} arms")
            return 0
        if mode in ("--export", "--json"):
            if len(argv) < 3:
                print(f"usage: armsfile.py {mode} <arm-id-or-key>", file=sys.stderr)
                return 1
            arm = find(argv[2])
            print(_export(arm) if mode == "--export" else json.dumps(arm, indent=2))
            return 0
    except ArmsError as error:
        print(f"arms.yaml: {error}", file=sys.stderr)
        return 1
    print(f"unknown option {mode!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
