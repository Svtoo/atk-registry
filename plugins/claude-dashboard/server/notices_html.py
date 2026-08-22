"""The only code that turns a notice into markup."""

from __future__ import annotations

import html

from notices import CLIENT_CODES, envelope


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _action(action: dict) -> str:
    label = _esc(action["label"])
    value = _esc(action["value"])
    if action["kind"] == "link":
        external = str(action["value"]).lower().startswith(("http://", "https://"))
        rel = ' target="_blank" rel="noopener noreferrer"' if external else ""
        return f'<a class="notice__action" href="{value}"{rel}>{label}</a>'
    return (f'<button type="button" class="notice__action" data-copy="{value}">'
            f"{label}</button>")


def _step(step: dict) -> str:
    parts = [f'<span class="notice__step-text">{_esc(step["text"])}</span>']
    if step.get("command"):
        cmd = _esc(step["command"])
        parts.append(
            f'<span class="notice__cmd"><code>{cmd}</code>'
            f'<button type="button" class="notice__copy" data-copy="{cmd}"'
            f' aria-label="Copy command">Copy</button></span>')
    if step.get("href"):
        label = _esc(step.get("hrefLabel") or step["href"])
        parts.append(f'<a class="notice__link" href="{_esc(step["href"])}">{label}</a>')
    return "<li>" + "".join(parts) + "</li>"


def _diagnostics(items: list) -> str:
    if not items:
        return ""
    rows = "".join(f"<dt>{_esc(d['label'])}</dt><dd>{_esc(d['value'])}</dd>"
                   for d in items)
    return f'<dl class="notice__diag">{rows}</dl>'


def _detail(env: dict) -> str:
    if not env.get("detail"):
        return ""
    raw = _esc(env["detail"])
    return (
        '<details class="notice__detail"><summary>Technical detail'
        f'<button type="button" class="notice__copy" data-copy="{raw}">Copy</button>'
        "</summary>"
        f'{_diagnostics(env.get("diagnostics") or [])}<pre>{raw}</pre></details>')


def render_one(env: dict) -> str:
    """One notice card; a resolved one keeps only its title, age and detail."""
    severity = _esc(env["severity"])
    resolved = env.get("resolvedAt") is not None
    head = [f'<span class="notice__title">{_esc(env["title"])}</span>']
    count = int(env.get("count") or 1)
    if count > 1:
        head.append(f'<span class="notice__count" title="happened {count} times">'
                    f"× {count}</span>")
    if env.get("at"):
        when = f'<time class="notice__when" data-at="{_esc(env["at"])}"'
        if resolved:
            when += f' data-resolved-at="{_esc(env["resolvedAt"])}"'
        head.append(when + "></time>")
    if env.get("dismiss") in ("ack", "auto"):
        head.append('<button type="button" class="notice__dismiss" data-dismiss>'
                    "✕ dismiss</button>")
    body = [f'<div class="notice__head">{"".join(head)}</div>']
    if not resolved:
        body.append(f'<p class="notice__what">{_esc(env["what"])}</p>')
        if env.get("steps"):
            body.append('<ol class="notice__steps">'
                        + "".join(_step(s) for s in env["steps"]) + "</ol>")
        if env.get("actions"):
            body.append('<div class="notice__actions">'
                        + "".join(_action(a) for a in env["actions"]) + "</div>")
        if env.get("explain"):
            body.append('<details class="notice__explain"><summary>'
                        "Why am I seeing this?</summary>"
                        f'<p>{_esc(env["explain"])}</p></details>')
    body.append(_detail(env))
    classes = f"notice notice--{severity}" + (" resolved" if resolved else "")
    return (f'<li class="{classes}" data-code="{_esc(env["code"])}"'
            f' data-notice-id="{_esc(env["id"])}" data-label="{_esc(env["label"])}"'
            f' data-dismiss-mode="{_esc(env["dismiss"])}">'
            + "".join(body) + "</li>")


def render_list(envs, *, group_label: str = "", resolved=()) -> str:
    """Every notice for one region, or an empty string so the region collapses.
    `resolved` entries fold behind a count."""
    cards = "".join(render_one(e) for e in envs or [])
    folded = "".join(render_one(e) for e in resolved or [])
    if not cards and not folded:
        return ""
    if folded:
        count = len(resolved)
        noun = "problem" if count == 1 else "problems"
        cards += (
            '<li class="notices__fold">'
            f'<button type="button" class="btn-quiet" data-fold-toggle>▸ {count} '
            f"earlier {noun} resolved on their own</button>"
            f'<ol class="notices__resolved" hidden>{folded}</ol></li>')
    heading = (f'<h2 class="notices__group">{_esc(group_label)}</h2>'
               if group_label else "")
    return f'{heading}<ol class="notices__list">{cards}</ol>'


def render_client_templates(codes=CLIENT_CODES) -> str:
    """Markup the browser clones for notices it raises itself, so they render
    with the server already unreachable."""
    return "".join(
        f'<template data-notice-code="{_esc(code)}">{render_one(envelope(code))}'
        "</template>"
        for code in codes or ())
