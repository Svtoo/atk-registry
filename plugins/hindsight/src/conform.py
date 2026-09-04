#!/usr/bin/env python3
"""Keep the configured bank's retain settings in line with ATK's configuration
without stomping changes the user made in the Hindsight UI or API.

ATK manages two keys: retain_extraction_mode and retain_custom_instructions.
Everything else on the bank is never touched. What ATK last wrote is recorded
in custom/.conform-state/<bank>.json, and each run compares three things: what ATK
wants (env + instructions file), what it last applied (the record), and what
the server holds (the bank's explicit overrides, which is also the surface the
web UI writes to).

  server matches the record   -> ATK still owns the keys; any change to ATK's
                                 configuration is applied and re-recorded.
  server differs from record  -> the user changed it; leave it alone and say so.
  no record, keys unset       -> fresh bank; apply ATK's defaults.
  no record, keys set         -> configured outside ATK; leave it alone.

--force reasserts ATK's configuration and re-records, whatever the server holds.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANAGED = ("retain_extraction_mode", "retain_custom_instructions")
# The tools SKILL.md tells the agent to call. The container env var narrows a
# container ATK runs; this list narrows the bank itself, which is the only
# route to an instance someone else runs.
TOOLS_KEY = "mcp_enabled_tools"
MCP_TOOLS = ["retain", "recall", "reflect", "list_memories", "list_mental_models",
             "get_mental_model", "create_mental_model", "update_mental_model",
             "refresh_mental_model", "clear_mental_model"]
MODES = ("concise", "verbose", "custom", "verbatim", "chunks", "off")
BANK_NAME = re.compile(r"[A-Za-z0-9._-]+")


def die(msg, hint=None):
    print(f"  ❌ {msg}", file=sys.stderr)
    if hint:
        print(f"  {hint}", file=sys.stderr)
    raise SystemExit(1)


def api(base, method, path, body=None):
    req = urllib.request.Request(base + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        die(f"{method} {path} returned {e.code}: {e.read().decode()[:200]}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        die(f"cannot reach Hindsight at {base}: {e}",
        "Is the service running? atk start hindsight")


def instructions_text():
    """custom/retain-instructions.md wins over the shipped default, matching the
    custom/ convention the compose override already uses."""
    for path in (os.path.join(PLUGIN_DIR, "custom", "retain-instructions.md"),
                 os.path.join(PLUGIN_DIR, "retain-instructions.md")):
        if os.path.exists(path):
            with open(path) as fh:
                text = fh.read().strip()
            if text:
                return text
    die("retain-instructions.md is missing or empty",
        "HINDSIGHT_RETAIN_MODE is 'custom', which needs instruction text.")


DIRECTIVE_NAME = "search-coverage"
DIRECTIVE_MODES = ("on", "off")


def directive_text():
    """custom/search-directive.md wins over the shipped default, like the
    retain instructions."""
    for path in (os.path.join(PLUGIN_DIR, "custom", "search-directive.md"),
                 os.path.join(PLUGIN_DIR, "search-directive.md")):
        if os.path.exists(path):
            with open(path) as fh:
                text = fh.read().strip()
            if text:
                return text
    die("search-directive.md is missing or empty",
        "HINDSIGHT_SEARCH_DIRECTIVE is 'on', which needs directive text.")


def desired_state(mode):
    desired = {"retain_extraction_mode": mode}
    if mode == "custom":
        desired["retain_custom_instructions"] = instructions_text()
    return desired


def managed_overrides(overrides):
    return {k: overrides[k] for k in MANAGED if overrides.get(k) is not None}


def state_path(bank):
    # custom/ is the one directory atk upgrade carries over.
    return os.path.join(PLUGIN_DIR, "custom", ".conform-state", f"{bank}.json")


def read_state(bank):
    try:
        with open(state_path(bank)) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None  # unreadable record: treat as absent, which never overwrites


def write_state(bank, **records):
    state = read_state(bank) or {}
    state.update(records)
    state = {k: v for k, v in state.items() if v is not None}
    os.makedirs(os.path.dirname(state_path(bank)), exist_ok=True)
    tmp = state_path(bank) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, state_path(bank))


def forget_state(bank):
    """What ATK once applied to a bank of this name says nothing about a bank
    that had to be created, so the record goes rather than reading as the
    user's own override."""
    try:
        os.remove(state_path(bank))
    except FileNotFoundError:
        pass


def apply(base, bank, desired, current):
    # Clearing uses an explicit null: a key ATK stops wanting (custom -> verbose
    # drops the instructions) must leave the bank, not linger as a stale override.
    updates = dict(desired)
    for key in MANAGED:
        if key not in desired and key in current:
            updates[key] = None
    api(base, "PATCH", f"/v1/default/banks/{bank}/config", {"updates": updates})
    write_state(bank, applied=desired)


def conform_tools(base, bank, force):
    """Narrow the bank's MCP surface to the tools the skill uses, and keep it
    there while ATK owns it; a list the user set is left alone."""
    path = f"/v1/default/banks/{bank}/config"
    on_server = (api(base, "GET", path)["overrides"] or {}).get(TOOLS_KEY)
    record = (read_state(bank) or {}).get("tools")
    if on_server is None or force or (on_server == record and on_server != MCP_TOOLS):
        api(base, "PATCH", path, {"updates": {TOOLS_KEY: MCP_TOOLS}})
        write_state(bank, tools=list(MCP_TOOLS))
        print(f"  bank '{bank}': MCP tools narrowed to the ones the skill uses")
        return
    if on_server == record:
        print(f"  bank '{bank}': MCP tools up to date")
        return
    print(f"  bank '{bank}': MCP tools were set outside ATK; leaving them alone.")
    print("     To hand them to ATK: ./conform.sh --force")


def conform_directive(base, bank, force):
    """Install the shipped search directive once and keep it current while ATK
    owns it; a directive the user edited on the server is left alone."""
    path = f"/v1/default/banks/{bank}/directives"
    text = directive_text()
    items = api(base, "GET", path).get("items") or []
    on_server = next((d for d in items if d.get("name") == DIRECTIVE_NAME), None)
    record = (read_state(bank) or {}).get("directive")
    if on_server is None:
        if record and not force:
            print(f"  bank '{bank}': search directive removed since ATK applied it; "
                  "treating that as your override and leaving it alone.")
            print("     To hand it back to ATK: ./conform.sh --force")
            return
        created = api(base, "POST", path, {"name": DIRECTIVE_NAME, "content": text})
        write_state(bank, directive={"id": created.get("id"), "content": text})
        print(f"  bank '{bank}': search directive installed")
        return
    owned = bool(record) and on_server.get("content") == record.get("content")
    if force or (owned and text != record["content"]):
        api(base, "PATCH", f"{path}/{on_server['id']}", {"content": text})
        write_state(bank, directive={"id": on_server["id"], "content": text})
        print(f"  bank '{bank}': search directive {'reasserted' if force else 'updated'}")
        return
    if owned:
        print(f"  bank '{bank}': search directive up to date")
        return
    if record:
        print(f"  bank '{bank}': search directive changed since ATK applied it; "
              "treating that as your override and leaving it alone.")
    else:
        print(f"  bank '{bank}': search directive was set outside ATK; leaving it alone.")
    print("     To hand it to ATK: ./conform.sh --force")


def retire_directive(base, bank):
    """Management switched off: remove the directive only if ATK installed it
    and the server still holds what ATK wrote."""
    path = f"/v1/default/banks/{bank}/directives"
    record = (read_state(bank) or {}).get("directive")
    if not record:
        print(f"  bank '{bank}': search-directive management is off; not touching it")
        return
    items = api(base, "GET", path).get("items") or []
    on_server = next((d for d in items if d.get("name") == DIRECTIVE_NAME), None)
    if on_server and on_server.get("content") == record.get("content"):
        api(base, "DELETE", f"{path}/{on_server['id']}")
        print(f"  bank '{bank}': search directive removed (management off)")
    else:
        print(f"  bank '{bank}': search-directive management is off; the directive "
              "on the server is not the one ATK wrote, leaving it alone")
    write_state(bank, directive=None)


def main():
    force = "--force" in sys.argv[1:]
    unknown = [a for a in sys.argv[1:] if a != "--force"]
    if unknown:
        die(f"unknown argument {unknown[0]!r}", "usage: conform.py [--force]")

    base = os.environ.get("HINDSIGHT_URL", "http://localhost:8888").rstrip("/")
    bank = os.environ.get("HINDSIGHT_BANK", "default")
    mode = os.environ.get("HINDSIGHT_RETAIN_MODE", "custom").strip().lower()
    if not BANK_NAME.fullmatch(bank):
        die(f"bank name {bank!r} may contain only letters, digits, dot, dash and underscore")
    if mode not in MODES:
        die(f"HINDSIGHT_RETAIN_MODE {mode!r} is not one of {', '.join(MODES)}")
    banks = [b["bank_id"] for b in api(base, "GET", "/v1/default/banks")["banks"]]
    if bank not in banks:
        api(base, "PUT", f"/v1/default/banks/{bank}", {})
        forget_state(bank)
        print(f"  created bank '{bank}'")

    conform_retain(base, bank, mode, force)
    conform_tools(base, bank, force)
    directive_mode = os.environ.get("HINDSIGHT_SEARCH_DIRECTIVE", "on").strip().lower()
    if directive_mode not in DIRECTIVE_MODES:
        die(f"HINDSIGHT_SEARCH_DIRECTIVE {directive_mode!r} is not one of {', '.join(DIRECTIVE_MODES)}")
    if directive_mode == "off":
        retire_directive(base, bank)
        return
    conform_directive(base, bank, force)


def conform_retain(base, bank, mode, force):
    if mode == "off":
        print(f"  bank '{bank}': retain-config management is off; not touching it")
        return
    desired = desired_state(mode)
    current = managed_overrides(api(base, "GET", f"/v1/default/banks/{bank}/config")["overrides"])
    state = read_state(bank)

    if force:
        apply(base, bank, desired, current)
        print(f"  bank '{bank}': retain config reasserted (mode={mode})")
        return

    if state is None:
        if current:
            print(f"  bank '{bank}': retain config was set outside ATK "
                  f"(mode={current.get('retain_extraction_mode', 'unset')}); leaving it alone.")
            print("     To hand it to ATK: ./conform.sh --force")
        else:
            apply(base, bank, desired, current)
            print(f"  bank '{bank}': retain config applied (mode={mode})")
        return

    if current != state.get("applied"):
        print(f"  bank '{bank}': retain config changed since ATK applied it "
              f"(now mode={current.get('retain_extraction_mode', 'unset')}); "
              "treating that as your override and leaving it alone.")
        print("     To hand it back to ATK: ./conform.sh --force")
        return

    if desired == current:
        print(f"  bank '{bank}': retain config up to date (mode={mode})")
        return

    apply(base, bank, desired, current)
    print(f"  bank '{bank}': retain config updated (mode={mode})")


if __name__ == "__main__":
    main()
