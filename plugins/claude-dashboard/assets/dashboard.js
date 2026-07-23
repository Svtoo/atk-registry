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
      if (!r.ok) return { acks: {} };
      const data = await r.json();
      return data && typeof data === "object" ? data : { acks: {} };
    } catch { return { acks: {} }; }
  }

  async function toggleAcknowledge(s, rowId, isAcknowledged) {
    const url = `/api/dashboard/${s.projectHash}/${s.sessionUuid}/acknowledge/${encodeURIComponent(rowId)}`;
    const method = isAcknowledged ? "DELETE" : "POST";
    const r = await fetch(url, { method, headers: { "Content-Type": "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
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
          // Re-fetch full sidecar so the new ackedAt sorts correctly.
          const sidecar = await fetchSidecar(s);
          applyAckState(sidecar.acks || {});
        } catch (e) {
          console.error("acknowledge failed", e);
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  async function initHeadsUp() {
    const s = currentSession();
    if (!s) return;            // not a per-chat dashboard
    if (!document.querySelector("table.watch-deck")) return;
    const sidecar = await fetchSidecar(s);
    applyAckState(sidecar.acks || {});
    wireAckButtons(s);
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
    initHeadsUp();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
