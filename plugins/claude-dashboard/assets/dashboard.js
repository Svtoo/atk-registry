/*
 * claude-dashboard — shared dashboard runtime.
 * Provides: theme management (system default + localStorage override),
 * auto-refresh on file change (preserves scroll), and Mermaid bootstrap.
 *
 * Loaded by per-chat dashboard.html via:
 *   <script src="http://localhost:7878/assets/dashboard.js" defer></script>
 *
 * The dashboard works without this script (just unstyled + no auto-refresh)
 * so it's a progressive enhancement, not a hard dependency.
 */
(function () {
  "use strict";

  const REFRESH_INTERVAL_MS = 30_000;
  const SCROLL_STORAGE_KEY = "claude-dashboard:scroll";
  const THEME_STORAGE_KEY = "claude-dashboard:theme";
  // Loaded from CDN (mermaid@10.9.1), lazily, only when a fragment contains a
  // .mermaid block. The dashboard CSP allowlists this host in script-src.
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

  // ─── Relative timestamps ─────────────────────────────────────────────
  function fmtRelative(iso) {
    const then = new Date(iso);
    if (isNaN(then.getTime())) return iso;
    const diff = Math.max(0, (Date.now() - then.getTime()) / 1000);
    if (diff < 5) return "just now";
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
    return then.toLocaleDateString();
  }
  function fmtTooltip(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    // e.g. "May 13, 2026, 10:01:20 AM PDT"
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "long" });
  }
  function updateRelativeTimes() {
    document.querySelectorAll("time[datetime]").forEach((el) => {
      const iso = el.getAttribute("datetime");
      if (!iso) return;
      const rel = fmtRelative(iso);
      // Preserve a "Updated " prefix if it was there; otherwise just render the relative time.
      const prefix = el.dataset.prefix || (el.textContent.trim().toLowerCase().startsWith("updated") ? "Updated " : "");
      el.dataset.prefix = prefix;
      el.textContent = prefix + rel;
      el.title = fmtTooltip(iso);
    });
  }

  // ─── Auto-refresh on file change + auto-update "Updated …" timestamp ─
  // The "Updated <relative>" line is driven entirely by the server's
  // Last-Modified header — the agent never has to set it. We poll HEAD
  // here, push the value into the <time datetime="…"> attribute, and
  // updateRelativeTimes() renders it as "Updated 1m ago" etc.
  let lastModified = null;
  function applyLastModified(lm) {
    const d = new Date(lm);
    if (isNaN(d.getTime())) return;
    document.querySelectorAll("time.updated").forEach((el) => {
      el.setAttribute("datetime", d.toISOString());
    });
    updateRelativeTimes();
  }
  async function checkForUpdates() {
    try {
      const res = await fetch(location.href, { method: "HEAD", cache: "no-store" });
      const lm = res.headers.get("Last-Modified");
      const etag = res.headers.get("ETag");
      const stamp = lm || etag;
      if (lm) applyLastModified(lm);
      if (stamp) {
        if (lastModified && stamp !== lastModified) {
          sessionStorage.setItem(SCROLL_STORAGE_KEY, String(window.scrollY));
          location.reload();
          return;
        }
        lastModified = stamp;
      }
    } catch (e) {
      // Server may be unreachable. Silently ignore — the dashboard still
      // renders, just without auto-refresh or the relative timestamp.
    }
  }

  // ─── Scroll preservation across reloads ──────────────────────────────
  function restoreScroll() {
    const y = sessionStorage.getItem(SCROLL_STORAGE_KEY);
    if (y !== null) {
      window.scrollTo(0, parseInt(y, 10) || 0);
      sessionStorage.removeItem(SCROLL_STORAGE_KEY);
      flashRefreshed();
    }
  }
  function flashRefreshed() {
    let el = document.querySelector(".refresh-flash");
    if (!el) {
      el = document.createElement("div");
      el.className = "refresh-flash";
      el.textContent = "↻ refreshed";
      document.body.appendChild(el);
    }
    el.classList.add("visible");
    setTimeout(() => el.classList.remove("visible"), 1500);
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
  // Each row in <table class="watch-deck"> with a data-row-id attribute
  // can be acknowledged by clicking its button. State is stored
  // server-side in <session_dir>/state.json (a generic per-chat
  // sidecar; ack state lives under the `acks` key). On load we fetch the
  // sidecar, mark acknowledged rows, and reorder them to the bottom.
  function parseSessionFromPath() {
    // Expected path: /<project-hash>/<session-uuid>/dashboard.html
    const m = location.pathname.match(/^\/([^/]+)\/([0-9a-fA-F-]{36})\/dashboard\.html$/);
    if (!m) return null;
    return { projectHash: m[1], sessionUuid: m[2] };
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
      // Reorder: fresh first (preserve agent's intended order), acknowledged
      // last (most recently acknowledged at the very bottom).
      acked.sort((a, b) => a.ackedAt - b.ackedAt);
      fresh.forEach((tr) => tbody.appendChild(tr));
      acked.forEach(({ tr }) => tbody.appendChild(tr));
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
    const s = parseSessionFromPath();
    if (!s) return;            // not a per-chat dashboard (no session in path)
    if (!document.querySelector("table.watch-deck")) return;
    const sidecar = await fetchSidecar(s);
    applyAckState(sidecar.acks || {});
    wireAckButtons(s);
  }

  // ─── Theme toggle button (injected into `[data-theme-slot]`) ────────
  // Looks for an existing `.theme-toggle` first; otherwise drops one
  // into the slot marked `[data-theme-slot]`, falling back to the first
  // `.actions` container if no explicit slot is declared.
  function wireThemeToggle() {
    let btn = document.querySelector(".theme-toggle");
    if (!btn) {
      const slot = document.querySelector("[data-theme-slot]") || document.querySelector(".actions");
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
    restoreScroll();
    wireThemeToggle();
    updateRelativeTimes();
    loadMermaid();
    initHeadsUp();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  setInterval(checkForUpdates, REFRESH_INTERVAL_MS);
  setInterval(updateRelativeTimes, REFRESH_INTERVAL_MS);
  // Prime the lastModified value on first load so we don't reload on first poll.
  checkForUpdates();
})();
