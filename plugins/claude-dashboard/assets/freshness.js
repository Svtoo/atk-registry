/*
 * claude-dashboard — freshness chip + rebuild trigger.
 *
 * Shared module used by BOTH the project-index (per-row chips) and the
 * per-dashboard layout shell (single chip in the topnav). Centralises the
 * state-to-chip mapping so we don't drift between the two surfaces.
 *
 * State model the server gives us per session:
 *   regen: {state: "running", since: <epoch>}    → currently regenerating
 *   regen: {state: "failed",  error: "..."}      → last run failed
 *   regen: null                                  → idle (no recent activity)
 * Combined with file mtimes:
 *   dashboardMtime ≥ jsonlMtime → "current" (no chip)
 *   else                        → "behind"  (only if no regen entry)
 *
 * Exposes a single `window.Freshness` namespace. No globals beyond that.
 */
(function () {
  "use strict";

  // Grace window before a "behind" chip appears. The server stamps the
  // dashboard a few seconds after the JSONL is written; under this window
  // it's noise, not a real lag.
  const BEHIND_GRACE_SECONDS = 90;

  function fmtAge(secs) {
    if (secs < 60) return Math.max(0, Math.floor(secs)) + "s";
    if (secs < 3600) return Math.floor(secs / 60) + "m";
    if (secs < 86400) return Math.floor(secs / 3600) + "h";
    return Math.floor(secs / 86400) + "d";
  }

  function escapeAttr(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // Returns an object describing the current freshness state. `info` is a
  // plain object with: hasDashboard, regen, mtime (jsonl epoch, noisy),
  // dashboardMtime (epoch), lastTurnEndedAt (epoch of last COMPLETED
  // agent turn, or null if a turn is in flight / no turn completed yet),
  // regenErrors (persisted error log; un-acked entries flip the chip).
  //
  // Precedence (highest wins):
  //   1. running             — a regen is in flight right now
  //   2. failed (persistent) — one or more un-acked regenErrors exist
  //   3. failed (transient)  — Registry's in-memory `failed` record
  //   4. behind              — dashboard predates the last completed turn
  //   5. current             — everything caught up
  //
  // Persistent errors win over transient because the Registry's "failed"
  // state gets cleared on the next trigger; the persisted entries are the
  // canonical record the user actually needs to dismiss deliberately.
  //
  // The "behind" comparison uses lastTurnEndedAt, NOT mtime — otherwise
  // typing a new user message immediately marks the dashboard "behind"
  // even though the agent hasn't finished its response yet and there's
  // literally nothing the regen subagent could do about it.
  function classify(info) {
    if (!info || !info.hasDashboard) {
      // No dashboard file yet. Don't blanket-hide: a first-gen that is RUNNING
      // or FAILED must be visible (that silent hole is exactly what made a
      // failed obsidian chat look like "nothing happened, no errors").
      const r0 = info && info.regen;
      if (r0 && r0.state === "running") {
        return {
          state: "running",
          label: "↻ generating · " + fmtAge((Date.now() / 1000) - r0.since),
          title: "The first dashboard is being generated.",
        };
      }
      const errs0 = ((info && info.regenErrors) || []).filter(e => e.ackedAt == null);
      if (errs0.length > 0 || (r0 && r0.state === "failed")) {
        return {
          state: "failed",
          label: "⚠ generation failed",
          title: "First dashboard generation failed — open the chat to see why, or rebuild.",
        };
      }
      return { state: "no-dashboard", label: "no dashboard", title: "" };
    }
    const r = info.regen;
    const nowS = Date.now() / 1000;
    if (r && r.state === "running") {
      const age = fmtAge(nowS - r.since);
      return {
        state: "running",
        label: "↻ updating · " + age,
        title: "Subagent is regenerating the dashboard.",
      };
    }
    const unackedErrors = (info.regenErrors || []).filter(e => e.ackedAt == null);
    if (unackedErrors.length > 0) {
      const noun = unackedErrors.length === 1 ? "error" : "errors";
      return {
        state: "failed",
        label: "⚠ " + unackedErrors.length + " regen " + noun,
        title: "Click rebuild or dismiss the entries in the banner below.",
      };
    }
    if (r && r.state === "failed") {
      return {
        state: "failed",
        label: "⚠ last update failed",
        title: (r.error || "(no detail)") + " — check runtime/server.log",
      };
    }
    // Behind only when a completed turn exists that the dashboard
    // doesn't reflect. `lastTurnEndedAt == null` means turn is in flight
    // or no turn ever finished — either way "behind" is meaningless.
    const dashMtime = info.dashboardMtime != null ? info.dashboardMtime : 0;
    if (info.lastTurnEndedAt != null) {
      const lag = info.lastTurnEndedAt - dashMtime;
      if (lag > BEHIND_GRACE_SECONDS) {
        return {
          state: "behind",
          label: "⚠ behind " + fmtAge(lag),
          title: "The dashboard predates the latest completed turn. Click rebuild to refresh.",
        };
      }
    }
    return {
      state: "current",
      label: "✓ current",
      title: "Dashboard is up to date with the latest completed turn.",
    };
  }

  // HTML for the chip. `state` from classify() drives a `.badge.<state>`
  // class so dashboard.css can colour it. Callers that don't want the
  // "current" chip should check the returned classification first.
  function chipHtml(info, opts) {
    const c = classify(info);
    const showCurrent = !!(opts && opts.showCurrent);
    if (c.state === "no-dashboard" || (c.state === "current" && !showCurrent)) {
      return "";
    }
    return '<span class="badge ' + c.state + '" title="' + escapeAttr(c.title) + '">' +
           escapeAttr(c.label) + '</span>';
  }

  // POST /api/regen for one session. Optimistic: caller decides what to
  // do with the response (e.g. re-fetch sessions list, swap chip).
  async function triggerRebuild(project, session) {
    const r = await fetch("/api/regen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: session, project: project }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  // ── Recents strip ──────────────────────────────────────────────
  // Used by BOTH the per-dashboard topnav and the project-index header.
  // The server hands back an enriched list; we render compact link-chips.
  // `currentKey` is `{project, session}` of the page you're currently
  // viewing (so we can mark "you are here" — null on the all-projects
  // index where there's no "current").

  function _truncTitle(title, max) {
    if (!title) return "(untitled chat)";
    return title.length > max ? title.slice(0, max - 1) + "…" : title;
  }

  // Render the chip list for one strip mode. `mode` is "recent" (queue,
  // ordered by openedAt) or "latest" (freshest dashboards across projects,
  // ordered by update time). The leading label is NOT emitted here — the
  // segmented toggle owns that slot now.
  function renderChips(list, currentKey, mode) {
    if (!Array.isArray(list) || list.length === 0) {
      const msg = mode === "latest" ? "no dashboards yet" : "nothing opened yet";
      return '<span class="strip-empty">' + msg + '</span>';
    }
    const parts = [];
    for (const r of list) {
      const isHere = currentKey
        && currentKey.project === r.sourceHash
        && currentKey.session === r.uuid;
      const href = "/" + r.sourceHash + "/" + r.uuid + "/dashboard.html";
      const cls = "chip" + (isHere ? " here" : "");
      const klass = classify(r);
      // Tiny dot conveys state without taking width; full chip lives on
      // the dashboard's own status group.
      const dot = klass.state === "running" ? '<span class="dot running" title="updating"></span>'
                : klass.state === "failed"  ? '<span class="dot failed"  title="last update failed"></span>'
                : klass.state === "behind"  ? '<span class="dot behind"  title="behind"></span>'
                : klass.state === "current" ? '<span class="dot current" title="current"></span>'
                : '';
      // Tooltip's time line reflects the axis: "updated" for latest,
      // "opened" for the recents queue.
      const whenLine = mode === "latest"
        ? "updated: " + new Date((r.dashboardMtime || 0) * 1000).toLocaleString()
        : "opened: " + new Date((r.openedAt || 0) * 1000).toLocaleString();
      const titleAttr = escapeAttr(
        (r.aiTitle || "(untitled chat)") +
        "\nproject: " + (r.projectLabel || r.sourceHash) +
        "\n" + whenLine
      );
      parts.push(
        '<a class="' + cls + '" href="' + escapeAttr(href) + '" title="' + titleAttr + '">' +
          dot +
          '<span class="chip-project">' + escapeAttr(r.projectLabel || "?") + '</span>' +
          '<span class="chip-title">' + escapeAttr(_truncTitle(r.aiTitle, 32)) + '</span>' +
        '</a>'
      );
    }
    return parts.join("");
  }

  async function fetchRecents() {
    const r = await fetch("/api/recents.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    return j.recents || [];
  }

  async function fetchLatest() {
    const r = await fetch("/api/latest.json", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const j = await r.json();
    return j.latest || [];
  }

  // ── Auth-health banner ─────────────────────────────────────────────
  // Surfaces the server's startup auth probe (GET /api/health.json). When the
  // regen subagent can't authenticate, NO dashboards generate — so we show a
  // page-wide banner on every surface rather than letting it read as silent
  // failure. Self-healing: clears the banner once health recovers.
  async function checkAuthHealth() {
    let h;
    try {
      const r = await fetch("/api/health.json", { cache: "no-store" });
      h = r.ok ? await r.json() : null;
    } catch (_) { return; }
    const existing = document.getElementById("ccd-auth-banner");
    if (!h || h.regenAuth !== "failed") {
      if (existing) existing.remove();
      return;
    }
    const banner = existing || document.createElement("div");
    if (!existing) {
      banner.id = "ccd-auth-banner";
      banner.className = "auth-banner";
      document.body.insertBefore(banner, document.body.firstChild);
    }
    banner.innerHTML =
      '<strong>⚠ Dashboard generation can’t authenticate.</strong> ' +
      'New dashboards won’t generate until this is resolved. ' +
      '<span class="auth-banner-detail">' + escapeAttr(h.detail || "") + '</span>';
  }

  // ── Toast notifications ────────────────────────────────────────
  // The recents poll is also the substrate for "a sibling chat just
  // finished updating" notifications. We track each non-current sibling's
  // last-seen regen state + dashboardMtime; transitions emit a toast.
  // On first tick we only build the baseline (no toasts) so the user
  // doesn't get a flood when they open a fresh page.

  const _siblingState = new Map(); // "p__s" -> { regenState, dashboardMtime }
  let _toastBootstrapped = false;

  function _snapshotSibling(r) {
    return {
      regenState: r.regen ? r.regen.state : null,
      dashboardMtime: r.dashboardMtime || 0,
    };
  }

  function _ensureToastRegion() {
    let region = document.getElementById("toast-region");
    if (!region) {
      region = document.createElement("div");
      region.id = "toast-region";
      region.className = "toast-region";
      document.body.appendChild(region);
    }
    return region;
  }

  function _truncForToast(s, max) {
    if (!s) return "(untitled chat)";
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

  function _showToast(opts) {
    const region = _ensureToastRegion();
    const toast = document.createElement("a");
    toast.className = "toast " + opts.kind;
    toast.href = opts.href;
    toast.innerHTML =
      '<span class="t-dot"></span>' +
      '<span class="t-msg">' +
        '<span class="t-line">' + escapeAttr(opts.message) + '</span>' +
        '<span class="t-meta">' +
          '<span class="t-project">' + escapeAttr(opts.project) + '</span>' +
          '<span class="t-title">' + escapeAttr(opts.title) + '</span>' +
        '</span>' +
      '</span>' +
      '<button class="t-close" type="button" aria-label="dismiss">×</button>';
    region.appendChild(toast);

    let dismissTimer = setTimeout(dismiss, 8000);
    function dismiss() { toast.remove(); }
    toast.addEventListener("mouseenter", () => clearTimeout(dismissTimer));
    toast.addEventListener("mouseleave", () => {
      clearTimeout(dismissTimer);
      dismissTimer = setTimeout(dismiss, 4000);
    });
    toast.querySelector(".t-close").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dismiss();
    });
  }

  function _emitTransitionToasts(recents, currentKey) {
    const seenThisTick = new Set();
    for (const r of recents) {
      const key = r.sourceHash + "__" + r.uuid;
      seenThisTick.add(key);
      const isCurrent = currentKey
        && currentKey.project === r.sourceHash
        && currentKey.session === r.uuid;
      if (isCurrent) {
        // Don't toast for the chat you're staring at — the in-place
        // chip + auto-reload already communicates state.
        _siblingState.set(key, _snapshotSibling(r));
        continue;
      }
      const prev = _siblingState.get(key);
      const curRegen = r.regen ? r.regen.state : null;
      const title = _truncForToast(r.aiTitle, 48);
      const project = r.projectLabel || "?";
      const href = "/" + r.sourceHash + "/" + r.uuid + "/dashboard.html";

      if (_toastBootstrapped) {
        if (!prev) {
          // Session newly entered the recents queue — happens when a
          // background regen succeeds for a chat the user never opened
          // (e.g. a child agent's first turn). Show it as a "new" toast.
          _showToast({
            kind: "success",
            message: "↪ new dashboard ready",
            title: title, project: project, href: href,
          });
        } else if (prev.regenState === "running") {
          if (curRegen === "failed") {
            _showToast({
              kind: "failed",
              message: "⚠ regen failed",
              title: title, project: project, href: href,
            });
          } else if (curRegen !== "running"
                     && (r.dashboardMtime || 0) > (prev.dashboardMtime || 0)) {
            _showToast({
              kind: "success",
              message: "✓ dashboard updated",
              title: title, project: project, href: href,
            });
          }
        }
      }
      _siblingState.set(key, _snapshotSibling(r));
    }
    // GC entries that fell off the back of the queue.
    for (const key of [..._siblingState.keys()]) {
      if (!seenThisTick.has(key)) _siblingState.delete(key);
    }
    _toastBootstrapped = true;
  }

  // Renders into `containerEl`. If anything in the list is "running",
  // returns true so callers can tighten their polling cadence.
  // Fetch + render one strip mode into `chipsEl`. Returns true if anything
  // is currently regenerating so the caller can tighten its poll cadence.
  // Toasts fire over whichever list is on screen — in "latest" mode that's
  // a superset of active siblings, so coverage is at least as good as the
  // recents-only behaviour it replaces.
  async function renderStrip(chipsEl, currentKey, mode) {
    if (!chipsEl) return false;
    let list = [];
    try {
      list = mode === "latest" ? await fetchLatest() : await fetchRecents();
    } catch (_) { /* keep current contents */ return false; }
    _emitTransitionToasts(list, currentKey);
    chipsEl.innerHTML = renderChips(list, currentKey, mode);
    return list.some(r => r.regen && r.regen.state === "running");
  }

  window.Freshness = {
    classify: classify,
    chipHtml: chipHtml,
    fmtAge: fmtAge,
    triggerRebuild: triggerRebuild,
    renderStrip: renderStrip,
    renderChips: renderChips,
    fetchRecents: fetchRecents,
    fetchLatest: fetchLatest,
    checkAuthHealth: checkAuthHealth,
    BEHIND_GRACE_SECONDS: BEHIND_GRACE_SECONDS,
  };

  // ── Auto-boot ─────────────────────────────────────────────────
  // Find #recents-strip on the page and run the polling loop. Reads the
  // current chat's (project, session) from data-attributes on the strip
  // so the dashboard view can highlight "you are here". The previous
  // setup put this loop in an inline body script — that ran during HTML
  // parse, BEFORE this deferred file had executed, and silently bailed
  // because window.Freshness was undefined. Self-booting here removes
  // the timing trap.
  // Strip mode persists per-browser so flipping to "latest" isn't undone on
  // every navigation — but the default is always "recent" (the history view
  // the user reaches for most), per Sasha's call.
  const STRIP_MODE_KEY = "ccd.stripMode";
  function getStripMode() {
    try {
      return localStorage.getItem(STRIP_MODE_KEY) === "latest" ? "latest" : "recent";
    } catch (_) { return "recent"; }
  }
  function setStripMode(m) {
    try { localStorage.setItem(STRIP_MODE_KEY, m); } catch (_) { /* private mode */ }
  }

  function _toggleHtml(mode) {
    function seg(m, text) {
      const on = m === mode ? " on" : "";
      return '<button type="button" class="seg' + on + '" data-mode="' + m + '"' +
             ' role="tab" aria-selected="' + (m === mode) + '">' + text + '</button>';
    }
    return '<span class="strip-toggle" role="tablist" aria-label="strip mode">' +
           seg("recent", "recent") + seg("latest", "latest") + '</span>';
  }

  function bootRecentsStrip() {
    const strip = document.getElementById("recents-strip");
    if (!strip) return;
    const project = strip.getAttribute("data-current-project") || null;
    const session = strip.getAttribute("data-current-session") || null;
    const currentKey = (project && session) ? { project, session } : null;

    let mode = getStripMode();
    // Static shell, built once: toggle slot + chips slot. Only the chips
    // slot re-renders on each tick.
    strip.innerHTML =
      '<span class="strip-toggle-slot"></span><span class="strip-chips"></span>';
    const toggleSlot = strip.querySelector(".strip-toggle-slot");
    const chipsEl = strip.querySelector(".strip-chips");
    function paintToggle() { toggleSlot.innerHTML = _toggleHtml(mode); }
    paintToggle();

    let timer = null;
    async function tick() {
      checkAuthHealth();  // page-wide auth banner; cheap, self-healing
      const anyRunning = await renderStrip(chipsEl, currentKey, mode);
      clearTimeout(timer);
      timer = setTimeout(tick, anyRunning ? 3000 : 30000);
    }

    toggleSlot.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-mode]");
      if (!btn) return;
      const next = btn.getAttribute("data-mode");
      if (next === mode) return;
      mode = next;
      setStripMode(mode);
      paintToggle();
      // Rebuild the toast baseline silently — without this, switching modes
      // treats the new list's members as "newly appeared" and floods toasts.
      _siblingState.clear();
      _toastBootstrapped = false;
      clearTimeout(timer);
      tick();
    });

    tick();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootRecentsStrip);
  } else {
    bootRecentsStrip();
  }
})();
