/* Notice regions: mounts the app-wide set from /api/notices.json, raises
 * client-side notices from pre-rendered templates, and handles copy, dismiss
 * and fold clicks for every region. Loaded on every page. */
(function () {
  "use strict";

  const POLL_MS = 30000;

  function region() { return document.getElementById("ccd-notices"); }

  function template(code) {
    return document.querySelector('template[data-notice-code="' + code + '"]');
  }

  function templateCard(code) {
    const t = template(code);
    return t ? t.content.querySelector("li.notice") : null;
  }

  function label(code) {
    const li = templateCard(code);
    return (li && li.getAttribute("data-label")) || "";
  }

  function title(code) {
    const li = templateCard(code);
    const el = li && li.querySelector(".notice__title");
    return (el && el.textContent) || "";
  }

  function fillAges(root) {
    if (!window.Freshness) return;
    root.querySelectorAll("time.notice__when[data-at]").forEach((el) => {
      const at = Number(el.getAttribute("data-at"));
      if (!at) return;
      const resolvedAt = Number(el.getAttribute("data-resolved-at"));
      el.textContent = resolvedAt
        ? "resolved " + window.Freshness.fmtAge(Math.max(0, resolvedAt - at)) + " later"
        : window.Freshness.fmtAge(Date.now() / 1000 - at) + " ago";
    });
  }

  // ── Client-raised notices (server unreachable, a click that failed) ──

  function localList(el) {
    let list = el.querySelector("ol[data-local-list]");
    if (!list) {
      list = document.createElement("ol");
      list.className = "notices__list";
      list.setAttribute("data-local-list", "");
      el.prepend(list);
    }
    return list;
  }

  function showLocal(code) {
    const el = region();
    if (!el || el.querySelector('[data-local="' + code + '"]')) return;
    const card = templateCard(code);
    if (!card) return;
    el.hidden = false;
    const li = card.cloneNode(true);
    li.setAttribute("data-local", code);
    const list = localList(el);
    list.appendChild(li);
    if (li.getAttribute("data-dismiss-mode") === "auto") {
      setTimeout(() => {
        li.remove();
        if (!list.children.length) list.remove();
      }, 6000);
    }
  }

  function clearLocal(code) {
    const el = region();
    if (!el) return;
    el.querySelectorAll('[data-local="' + code + '"]').forEach((n) => n.remove());
    const list = el.querySelector("ol[data-local-list]");
    if (list && !list.children.length) list.remove();
  }

  function fetchFailed(err) {
    showLocal(err instanceof TypeError ? "net.server_down" : "net.page_failed");
  }

  // ── App-scope polling ──

  let generation = null;
  let pollSeq = 0;

  function mountApp(gen, html) {
    const el = region();
    if (!el || String(gen) === generation) return;
    generation = String(gen);
    const locals = el.querySelector("ol[data-local-list]");
    el.innerHTML = html || "";
    if (locals && locals.children.length) el.prepend(locals);
    el.hidden = false;
    fillAges(el);
  }

  async function poll() {
    const seq = ++pollSeq;
    let payload;
    try {
      const r = await fetch("/api/notices.json", { cache: "no-store" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      payload = await r.json();
    } catch (e) {
      if (seq === pollSeq) fetchFailed(e);
      return;
    }
    if (seq !== pollSeq) return;
    clearLocal("net.server_down");
    clearLocal("net.page_failed");
    mountApp(payload.generation, payload.html);
  }

  // ── Clicks: fold, copy, dismiss — one delegate for every region ──

  const dismissHandlers = new WeakMap();

  function onDismiss(regionEl, fn) { dismissHandlers.set(regionEl, fn); }

  document.addEventListener("click", async (ev) => {
    const foldBtn = ev.target.closest("[data-fold-toggle]");
    if (foldBtn) {
      const list = foldBtn.nextElementSibling;
      if (list) {
        list.hidden = !list.hidden;
        foldBtn.textContent = (list.hidden ? "▸" : "▾") + foldBtn.textContent.slice(1);
      }
      return;
    }

    const copyBtn = ev.target.closest("[data-copy]");
    if (copyBtn) {
      if (copyBtn.closest("summary")) ev.preventDefault();
      const original = copyBtn.textContent;
      let copied = true;
      try {
        await navigator.clipboard.writeText(copyBtn.getAttribute("data-copy") || "");
      } catch (_) {
        copied = false;
      }
      copyBtn.textContent = copied ? "Copied" : "Copy failed";
      setTimeout(() => { copyBtn.textContent = original; }, 1200);
      return;
    }

    const dismissBtn = ev.target.closest("[data-dismiss]");
    if (!dismissBtn) return;
    const li = dismissBtn.closest("li.notice");
    const root = li && li.closest(".notices");
    if (!li || !root) return;
    const handler = dismissHandlers.get(root);
    dismissBtn.disabled = true;
    try {
      if (handler) await handler(li);
      li.remove();
      if (!root.querySelector("li.notice")) {
        root.innerHTML = "";
        root.hidden = true;
      }
    } catch (_) {
      dismissBtn.disabled = false;
      showLocal("net.action_failed");
    }
  });

  window.Notices = {
    showLocal, clearLocal, fetchFailed, fillAges, label, title, onDismiss,
  };

  function boot() {
    const el = region();
    if (!el) return;
    generation = el.getAttribute("data-generation");
    fillAges(el);
    setInterval(poll, POLL_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) poll();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
