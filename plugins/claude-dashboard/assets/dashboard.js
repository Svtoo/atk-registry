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
    return localStorage.getItem(THEME_STORAGE_KEY) || "system";
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
    localStorage.setItem(THEME_STORAGE_KEY, next);
    applyTheme();
  }
  // Re-apply when system theme changes (only matters if pref === "system")
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (storedThemePref() === "system") applyTheme();
    });
  }

  // ─── Mermaid bootstrap (load CDN, init with theme-matched palette) ──
  function loadMermaid() {
    if (document.querySelector('pre.mermaid, .mermaid') == null) return;
    if (window.mermaid) {
      window.mermaid.initialize({
        startOnLoad: true,
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
        flowchart: { curve: "basis" },
      });
      return;
    }
    const s = document.createElement("script");
    s.src = MERMAID_SRC;
    s.onload = () => {
      window.mermaid.initialize({
        startOnLoad: true,
        theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
        flowchart: { curve: "basis" },
      });
    };
    document.head.appendChild(s);
  }

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
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

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
    "ul.todo-list > li[data-item-id], ol.questions-list > li[data-item-id]";

  function verdictSection(li) {
    return li.closest("ol.questions-list") ? "cta" : "todo";
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
    document.querySelectorAll(VERDICT_ROWS).forEach((li) => {
      const v = verdicts[verdictSection(li) + ":" + li.getAttribute("data-item-id")];
      const userDone = Boolean(v && v.verdict === "done");
      const stubbed = Boolean(v) && !userDone;
      li.classList.toggle("done", userDone);
      li.classList.toggle("user-done", userDone);
      li.classList.toggle("verdict-stub", stubbed);
      const check = li.querySelector("button.todo-check");
      if (check) check.classList.toggle("checked", userDone);
      const trash = li.querySelector("button.verdict-btn.trash");
      if (trash) {
        trash.setAttribute("aria-label", stubbed ? "undo" : trash.dataset.verdict === "dismissed" ? "dismiss" : "drop");
        trash.setAttribute("title", stubbed ? "undo" : trash.dataset.verdict === "dismissed" ? "dismiss" : "drop (no longer relevant)");
        trash.classList.toggle("undoing", stubbed);
      }
    });
  }

  function wireVerdictButtons(s) {
    document.querySelectorAll(VERDICT_ROWS).forEach((li) => {
      li.querySelectorAll("button.todo-check, button.verdict-btn.trash").forEach((btn) => {
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
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
