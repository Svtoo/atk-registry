/* Shared page runtime: theme toggle, heads-up acknowledge handling, and
 * Mermaid bootstrap. Loaded on every page via templates/_head.html. */
(function () {
  "use strict";

  const THEME_STORAGE_KEY = "claude-dashboard:theme";
  // The CSP allowlists this host in script-src.
  const MERMAID_SRC = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js";

  // ─── Theme ───────────────────────────────────────────────────────────
  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }
  function storedThemePref() {
    try {
      return localStorage.getItem(THEME_STORAGE_KEY) || "system";
    } catch (_) { return "system"; }
  }
  function effectiveTheme(pref) {
    return pref === "system" ? systemTheme() : pref;
  }
  function applyTheme() {
    const pref = storedThemePref();
    const eff = effectiveTheme(pref);
    document.documentElement.dataset.theme = eff;
    const btn = document.querySelector(".theme-toggle");
    if (btn) {
      const label = pref === "system" ? "🌓 system" : (eff === "dark" ? "🌙 dark" : "☀️ light");
      btn.textContent = label;
    }
  }
  function cycleTheme() {
    const order = ["system", "light", "dark"];
    const next = order[(order.indexOf(storedThemePref()) + 1) % order.length];
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (_) { /* private mode */ }
    applyTheme();
  }
  // Re-apply when system theme changes (only matters if pref === "system")
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (storedThemePref() === "system") applyTheme();
    });
  }

  // ─── Mermaid bootstrap (load CDN, init with theme-matched palette) ──
  function mermaidConfig() {
    return {
      startOnLoad: false,
      theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
      flowchart: { curve: "basis" },
    };
  }

  function loadMermaid() {
    if (document.querySelector('pre.mermaid, .mermaid') == null) return;
    if (window.mermaid) {
      window.mermaid.initialize(mermaidConfig());
      renderDiagrams();
      return;
    }
    const s = document.createElement("script");
    s.src = MERMAID_SRC;
    s.onerror = () => {
      if (window.Notices) window.Notices.showLocal("net.diagram_failed");
    };
    s.onload = () => {
      window.mermaid.initialize(mermaidConfig());
      renderDiagrams();
    };
    document.head.appendChild(s);
  }

  // ─── Diagram validation: render what parses, flag what doesn't ───────
  // A broken diagram becomes a quiet chip instead of mermaid's error bomb,
  // and the failure is reported to the sidecar so the agent repairs the card
  // on the next rebuild.
  function slotIdOf(pre) {
    const slot = pre.closest(".freeform-slot");
    return slot ? slot.getAttribute("data-item-id") : null;
  }

  async function renderDiagrams() {
    const results = new Map();
    for (const pre of document.querySelectorAll("pre.mermaid")) {
      const id = slotIdOf(pre);
      let ok = true;
      try { await window.mermaid.parse(pre.textContent); } catch { ok = false; }
      if (!ok) {
        const chip = document.createElement("div");
        chip.className = "diagram-failed";
        chip.textContent = "⚠ diagram failed to render — flagged for repair on the next update";
        pre.replaceWith(chip);
        if (id) results.set(id, false);
        continue;
      }
      try { await window.mermaid.run({ nodes: [pre] }); } catch { /* parse passed; leave the block as is */ }
      if (id && results.get(id) !== false) results.set(id, true);
    }
    reconcileDiagramErrors(results);
  }

  async function reconcileDiagramErrors(results) {
    const s = currentSession();
    if (!s || results.size === 0) return;
    const sidecar = await fetchSidecar(s);
    if (!sidecar) return;
    const flagged = sidecar.diagramErrors || {};
    for (const [id, ok] of results) {
      const url = `/api/dashboard/${s.projectHash}/${s.sessionUuid}/diagram-error/${encodeURIComponent(id)}`;
      try {
        if (!ok && !flagged[id]) await sidecarMutate(url, "POST");
        else if (ok && flagged[id]) await sidecarMutate(url, "DELETE");
      } catch { /* best-effort; the next page load retries */ }
    }
  }

  // ─── Mermaid lightbox: click a diagram to inspect it full-screen ─────
  function closeDiagramLightbox() {
    const box = document.querySelector(".mermaid-lightbox");
    if (box) box.remove();
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest) return;
    const pre = e.target.closest("pre.mermaid");
    if (pre) {
      const svg = pre.querySelector("svg");
      if (!svg) return;
      closeDiagramLightbox();
      const box = document.createElement("div");
      box.className = "mermaid-lightbox";
      const clone = svg.cloneNode(true);
      clone.removeAttribute("width");
      clone.removeAttribute("height");
      clone.style.maxWidth = "none";
      box.appendChild(clone);
      document.body.appendChild(box);
      return;
    }
    if (e.target.closest(".mermaid-lightbox")) closeDiagramLightbox();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDiagramLightbox();
  });

  // ─── Heads-up acknowledge handling ───────────────────────────────────
  // Ack state lives server-side in the per-chat state.json sidecar.
  function currentSession() {
    // The per-chat layout stamps its ids on #recents-strip; browse pages don't.
    const strip = document.getElementById("recents-strip");
    const projectHash = strip && strip.getAttribute("data-current-project");
    const sessionUuid = strip && strip.getAttribute("data-current-session");
    return projectHash && sessionUuid ? { projectHash, sessionUuid } : null;
  }

  async function fetchSidecar(s) {
    try {
      const r = await fetch(`/api/dashboard/${s.projectHash}/${s.sessionUuid}.json`, { cache: "no-store" });
      if (!r.ok) return null;
      const data = await r.json();
      return data && typeof data === "object" ? data : null;
    } catch { return null; }
  }

  async function sidecarMutate(url, method, body) {
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
  }

  // Out-of-order responses must not repaint over newer state; a failed
  // re-fetch keeps the current DOM rather than painting from nothing.
  let sidecarSeq = 0;
  async function refreshSidecar(s) {
    const seq = ++sidecarSeq;
    const sidecar = await fetchSidecar(s);
    if (!sidecar || seq !== sidecarSeq) return;
    applyAckState(sidecar.acks || {});
    applyVerdictState(sidecar.verdicts || {});
  }

  function toggleAcknowledge(s, rowId, isAcknowledged) {
    const url = `/api/dashboard/${s.projectHash}/${s.sessionUuid}/acknowledge/${encodeURIComponent(rowId)}`;
    return sidecarMutate(url, isAcknowledged ? "DELETE" : "POST");
  }

  function applyAckState(acks) {
    const tables = document.querySelectorAll("table.watch-deck");
    tables.forEach((table) => {
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const oldToggle = tbody.querySelector("tr.acked-toggle");
      if (oldToggle) oldToggle.remove();
      const rows = Array.from(tbody.querySelectorAll("tr[data-row-id]"));
      const fresh = [];
      const acked = [];
      rows.forEach((tr) => {
        const id = tr.getAttribute("data-row-id");
        const ackInfo = acks[id];
        const btn = tr.querySelector("button.ack-btn");
        if (ackInfo) {
          tr.classList.add("acked");
          if (btn) {
            btn.classList.add("acked");
            btn.textContent = "✓ acknowledged · undo";
            btn.dataset.acked = "1";
          }
          acked.push({ tr, ackedAt: ackInfo.ackedAt || 0 });
        } else {
          tr.classList.remove("acked");
          if (btn) {
            btn.classList.remove("acked");
            btn.textContent = "acknowledge";
            btn.dataset.acked = "0";
          }
          fresh.push(tr);
        }
      });
      acked.sort((a, b) => a.ackedAt - b.ackedAt);
      fresh.forEach((tr) => tbody.appendChild(tr));
      acked.forEach(({ tr }) => tbody.appendChild(tr));

      if (acked.length === 0) {
        table.classList.remove("acked-folded");
        return;
      }
      const folded = table.dataset.ackedExpanded !== "1";   // default: folded
      table.classList.toggle("acked-folded", folded);
      const label = (f) => (f ? "▸ Show " : "▾ Hide ") + acked.length +
        " acknowledged item" + (acked.length === 1 ? "" : "s");
      const toggle = document.createElement("tr");
      toggle.className = "acked-toggle";
      const td = document.createElement("td");
      td.colSpan = (table.tHead && table.tHead.rows[0]) ? table.tHead.rows[0].cells.length : 5;
      td.textContent = label(folded);
      toggle.appendChild(td);
      tbody.insertBefore(toggle, acked[0].tr);   // toggle sits above the folded rows
      toggle.addEventListener("click", () => {
        const nowFolded = table.classList.toggle("acked-folded");
        table.dataset.ackedExpanded = nowFolded ? "0" : "1";
        td.textContent = label(nowFolded);
      });
    });
  }

  function wireAckButtons(s) {
    const buttons = document.querySelectorAll("table.watch-deck button.ack-btn");
    buttons.forEach((btn) => {
      btn.addEventListener("click", async () => {
        const tr = btn.closest("tr[data-row-id]");
        if (!tr) return;
        const rowId = tr.getAttribute("data-row-id");
        const isAcknowledged = btn.dataset.acked === "1";
        btn.disabled = true;
        try {
          await toggleAcknowledge(s, rowId, isAcknowledged);
          await refreshSidecar(s);
        } catch (e) {
          console.error("acknowledge failed", e);
          if (window.Notices) window.Notices.showLocal("net.action_failed");
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  // Copy buttons ride the page-wide [data-copy] click handler in notices.js.
  async function initHeadsUp(s, sidecar) {
    if (!document.querySelector("table.watch-deck")) return;
    applyAckState(sidecar.acks || {});
    wireAckButtons(s);
  }

  // ─── User verdicts on to-do / CTA items ──────────────────────────────
  // Server-side state like acks. A dropped/dismissed row collapses to an
  // undo stub until the next regen removes the item from the markup.
  // Selectors stay scoped to the server-rendered lists; agent-authored
  // freeform HTML must never acquire verdict wiring.
  const VERDICT_ROWS =
    "ul.todo-list > li[data-item-id], ol.questions-list > li[data-item-id], " +
    "div.freeform-slot[data-item-id]:not(.dismissed)";

  function verdictSection(el) {
    if (el.classList.contains("freeform-slot")) return "freeform";
    return el.closest("ol.questions-list") ? "cta" : "todo";
  }

  function setVerdict(s, li, verdict) {
    const url = `/api/dashboard/${s.projectHash}/${s.sessionUuid}` +
      `/verdict/${verdictSection(li)}/` +
      encodeURIComponent(li.getAttribute("data-item-id"));
    return verdict
      ? sidecarMutate(url, "POST", { verdict })
      : sidecarMutate(url, "DELETE");
  }

  function applyVerdictState(verdicts) {
    document.querySelectorAll(VERDICT_ROWS).forEach((el) => {
      const v = verdicts[verdictSection(el) + ":" + el.getAttribute("data-item-id")];
      const stubbed = Boolean(v) && v.verdict !== "done";
      if (el.classList.contains("freeform-slot")) {
        el.classList.toggle("verdict-stub", stubbed);
        const x = el.querySelector("button.ff-dismiss");
        if (x) {
          x.textContent = stubbed ? "dismissed · undo" : "✕";
          x.setAttribute("aria-label", stubbed ? "undo" : "dismiss");
          x.setAttribute("title", stubbed ? "undo" : "dismiss");
          x.classList.toggle("undoing", stubbed);
        }
        return;
      }
      const userDone = Boolean(v && v.verdict === "done");
      el.classList.toggle("done", userDone);
      el.classList.toggle("user-done", userDone);
      el.classList.toggle("verdict-stub", stubbed);
      const check = el.querySelector("button.todo-check");
      if (check) check.classList.toggle("checked", userDone);
      const trash = el.querySelector("button.verdict-btn.trash");
      if (trash) {
        trash.setAttribute("aria-label", stubbed ? "undo" : trash.dataset.verdict === "dismissed" ? "dismiss" : "drop");
        trash.setAttribute("title", stubbed ? "undo" : trash.dataset.verdict === "dismissed" ? "dismiss" : "drop (no longer relevant)");
        trash.classList.toggle("undoing", stubbed);
      }
    });
  }

  function wireVerdictButtons(s) {
    document.querySelectorAll(VERDICT_ROWS).forEach((li) => {
      li.querySelectorAll("button.todo-check, button.verdict-btn.trash, button.ff-dismiss").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const undoing = btn.classList.contains("todo-check")
            ? btn.classList.contains("checked")
            : li.classList.contains("verdict-stub");
          btn.disabled = true;
          try {
            await setVerdict(s, li, undoing ? null : btn.dataset.verdict);
            await refreshSidecar(s);
          } catch (e) {
            console.error("verdict failed", e);
            if (window.Notices) window.Notices.showLocal("net.action_failed");
          } finally {
            btn.disabled = false;
          }
        });
      });
    });
  }

  function initVerdicts(s, sidecar) {
    if (!document.querySelector(VERDICT_ROWS)) return;
    applyVerdictState(sidecar.verdicts || {});
    wireVerdictButtons(s);
  }

  async function initSidecar() {
    const s = currentSession();
    if (!s) return;            // not a per-chat dashboard
    const sidecar = await fetchSidecar(s) || { acks: {}, verdicts: {} };
    initHeadsUp(s, sidecar);
    initVerdicts(s, sidecar);
  }

  // ─── Dismissed freeform fold ─────────────────────────────────────────
  // Server-dismissed cards stay viewable history behind a toggle, out of
  // the agent's context.
  function foldDismissedFreeform() {
    const old = document.querySelector(".ff-fold-toggle");
    if (old) old.remove();
    const dismissed = document.querySelectorAll("div.freeform-slot.dismissed");
    if (dismissed.length === 0) return;
    const label = (shown) => (shown ? "▾ Hide " : "▸ Show ") + dismissed.length +
      " dismissed card" + (dismissed.length === 1 ? "" : "s");
    const toggle = document.createElement("div");
    toggle.className = "ff-fold-toggle";
    let shown = false;
    toggle.textContent = label(shown);
    dismissed[0].parentNode.insertBefore(toggle, dismissed[0]);
    toggle.addEventListener("click", () => {
      shown = !shown;
      dismissed.forEach((el) => el.classList.toggle("shown", shown));
      toggle.textContent = label(shown);
    });
  }

  // ─── Done to-dos fold ────────────────────────────────────────────────
  // Done rows are permanent history; they collapse behind a count the same
  // way acknowledged heads-up rows do. User-checked rows stay visible until
  // a regen absorbs them.
  function foldDoneTodos() {
    document.querySelectorAll("ul.todo-list").forEach((ul) => {
      const oldToggle = ul.querySelector("li.done-toggle");
      if (oldToggle) oldToggle.remove();
      const done = ul.querySelectorAll("li.done:not(.user-done)");
      if (done.length === 0) {
        ul.classList.remove("done-folded");
        return;
      }
      const folded = ul.dataset.doneExpanded !== "1";   // default: folded
      ul.classList.toggle("done-folded", folded);
      const label = (f) => (f ? "▸ Show " : "▾ Hide ") + done.length +
        " done item" + (done.length === 1 ? "" : "s");
      const li = document.createElement("li");
      li.className = "done-toggle";
      li.textContent = label(folded);
      ul.insertBefore(li, done[0]);
      li.addEventListener("click", () => {
        const nowFolded = ul.classList.toggle("done-folded");
        ul.dataset.doneExpanded = nowFolded ? "0" : "1";
        li.textContent = label(nowFolded);
      });
    });
  }

  // ─── Theme toggle button (injected into `[data-theme-slot]`) ────────
  function wireThemeToggle() {
    let btn = document.querySelector(".theme-toggle");
    if (!btn) {
      const slot = document.querySelector("[data-theme-slot]");
      if (slot) {
        btn = document.createElement("button");
        btn.className = "theme-toggle";
        btn.type = "button";
        slot.appendChild(btn);
      }
    }
    if (btn) {
      btn.addEventListener("click", cycleTheme);
      applyTheme();
    }
  }

  // ─── Init ────────────────────────────────────────────────────────────
  applyTheme();
  function init() {
    wireThemeToggle();
    loadMermaid();
    initSidecar();
    foldDoneTodos();
    foldDismissedFreeform();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
