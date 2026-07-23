/* Freshness chips, rebuild trigger, recents strip, toasts, auth banner:
 * the `window.Freshness` namespace, loaded on every page. */
(function () {
  "use strict";

  // The server stamps the dashboard a few seconds after the JSONL is written;
  // under this window "behind" is noise, not real lag.
  const BEHIND_GRACE_SECONDS = 90;

  function fmtAge(secs) {
    if (secs < 60) return Math.max(0, Math.floor(secs)) + "s";
    if (secs < 3600) return Math.floor(secs / 60) + "m";
    if (secs < 86400) return Math.floor(secs / 3600) + "h";
    return Math.floor(secs / 86400) + "d";
  }

  function fmtDateParts(iso) {
    const d = new Date(iso);
    return {
      date: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      time: d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }),
    };
  }

  function fmtDate(iso) {
    const p = fmtDateParts(iso);
    return p.date + " " + p.time;
  }

  function fmtTokens(n) {
    if (n == null) return "?";
    return n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n);
  }

  function dashboardHref(projectHash, sessionUuid) {
    return "/" + projectHash + "/" + sessionUuid + "/dashboard.html";
  }

  function setPageStatus(ok) {
    const el = document.getElementById("status");
    if (!el) return;
    el.className = ok ? "status live" : "status dead";
    el.innerHTML = '<span class="dot"></span>' + (ok ? "live" : "server down");
  }

  function stampUpdated() {
    const el = document.getElementById("updated");
    if (!el) return;
    el.innerHTML = "<strong>" + new Date().toLocaleTimeString(
      "en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "</strong>";
  }

  // `info` per session: hasDashboard, regen ({state, since|error} | null),
  // mtime, dashboardMtime, lastTurnEndedAt, regenErrors.
  //
  // Precedence (highest wins):
  //   1. running:  a regen is in flight right now
  //   2. failed (persistent):  one or more un-acked regenErrors exist
  //   3. failed (transient):  the Registry's in-memory failed record
  //   4. behind:  the dashboard predates the last completed turn
  //   5. current:  everything caught up
  //
  // "Behind" compares against lastTurnEndedAt, not mtime: the file mtime also
  // advances on user-typed messages and tool_results, which no regen can act on.
  function classify(info) {
    if (!info || !info.hasDashboard) {
      // A first generation that is running or failed must still show a chip.
      const r0 = info && info.regen;
      if (r0 && r0.state === "running") {
        return {
          state: "running",
          label: "↻ generating · " + fmtAge((Date.now() / 1000) - r0.since),
          title: "The first dashboard is being generated.",
        };
      }
      const errs0 = ((info && info.regenErrors) || []).filter(e => e.ackedAt == null && e.resolvedAt == null);
      if (errs0.length > 0 || (r0 && r0.state === "failed")) {
        return {
          state: "failed",
          label: "⚠ generation failed",
          title: "First dashboard generation failed. Open the chat to see why, or rebuild.",
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
    const unackedErrors = (info.regenErrors || []).filter(e => e.ackedAt == null && e.resolvedAt == null);
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
        title: (r.error || "(no detail)") + "; check runtime/server.log",
      };
    }
    // lastTurnEndedAt == null means a turn is in flight or none ever finished;
    // "behind" is meaningless then.
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

  function chipHtml(info, opts) {
    const c = classify(info);
    const showCurrent = !!(opts && opts.showCurrent);
    if (c.state === "no-dashboard" || (c.state === "current" && !showCurrent)) {
      return "";
    }
    return '<span class="badge ' + c.state + '" title="' + escapeHtml(c.title) + '">' +
           escapeHtml(c.label) + '</span>';
  }

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

  function _trunc(s, max) {
    if (!s) return "(untitled chat)";
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  }

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
      const href = dashboardHref(r.sourceHash, r.uuid);
      const cls = "chip" + (isHere ? " here" : "");
      const klass = classify(r);
      const dot = klass.state === "running" ? '<span class="dot running" title="updating"></span>'
                : klass.state === "failed"  ? '<span class="dot failed"  title="last update failed"></span>'
                : klass.state === "behind"  ? '<span class="dot behind"  title="behind"></span>'
                : klass.state === "current" ? '<span class="dot current" title="current"></span>'
                : '';
      const whenLine = mode === "latest"
        ? "updated: " + new Date((r.dashboardMtime || 0) * 1000).toLocaleString()
        : "opened: " + new Date((r.openedAt || 0) * 1000).toLocaleString();
      const titleAttr = escapeHtml(
        (r.aiTitle || "(untitled chat)") +
        "\nproject: " + (r.projectLabel || r.sourceHash) +
        "\n" + whenLine
      );
      // The short date keeps same-titled chats tellable apart at a glance.
      const when = fmtDateParts(r.mtimeIso || 0).date;
      parts.push(
        '<a class="' + cls + '" href="' + escapeHtml(href) + '" title="' + titleAttr + '">' +
          dot +
          '<span class="chip-project">' + escapeHtml(r.projectLabel || "?") + '</span>' +
          '<span class="chip-title">' + escapeHtml(_trunc(r.aiTitle, 32)) + '</span>' +
          '<span class="chip-when">' + escapeHtml(when) + '</span>' +
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
  // When the regen subagent cannot authenticate, no dashboards generate;
  // the banner clears itself once /api/health.json recovers.
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
      '<span class="auth-banner-detail">' + escapeHtml(h.detail || "") + '</span>';
  }

  // ── Toast notifications ────────────────────────────────────────
  // The recents poll doubles as the change feed for sibling chats. The first
  // tick only builds the baseline, so opening a page never floods toasts.

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

  function _showToast(opts) {
    const region = _ensureToastRegion();
    const toast = document.createElement("a");
    toast.className = "toast " + opts.kind;
    toast.href = opts.href;
    toast.innerHTML =
      '<span class="t-dot"></span>' +
      '<span class="t-msg">' +
        '<span class="t-line">' + escapeHtml(opts.message) + '</span>' +
        '<span class="t-meta">' +
          '<span class="t-project">' + escapeHtml(opts.project) + '</span>' +
          '<span class="t-title">' + escapeHtml(opts.title) + '</span>' +
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
        // The chat on screen already shows its state in place.
        _siblingState.set(key, _snapshotSibling(r));
        continue;
      }
      const prev = _siblingState.get(key);
      const curRegen = r.regen ? r.regen.state : null;
      const title = _trunc(r.aiTitle, 48);
      const project = r.projectLabel || "?";
      const href = dashboardHref(r.sourceHash, r.uuid);

      if (_toastBootstrapped) {
        if (!prev) {
          // A session the user never opened entered the queue: a background
          // regen succeeded for it.
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
    for (const key of [..._siblingState.keys()]) {
      if (!seenThisTick.has(key)) _siblingState.delete(key);
    }
    _toastBootstrapped = true;
  }

  // Returns true when anything is regenerating so the caller can poll faster.
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
    fmtDate: fmtDate,
    fmtDateParts: fmtDateParts,
    fmtTokens: fmtTokens,
    dashboardHref: dashboardHref,
    setPageStatus: setPageStatus,
    stampUpdated: stampUpdated,
    triggerRebuild: triggerRebuild,
  };

  // ── Auto-boot ─────────────────────────────────────────────────
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
    // Static shell built once; only the chips slot re-renders per tick.
    strip.innerHTML =
      '<span class="strip-toggle-slot"></span><span class="strip-chips"></span>';
    const toggleSlot = strip.querySelector(".strip-toggle-slot");
    const chipsEl = strip.querySelector(".strip-chips");
    function paintToggle() { toggleSlot.innerHTML = _toggleHtml(mode); }
    paintToggle();

    let timer = null;
    async function tick() {
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
      // Rebuild the toast baseline silently; otherwise the new list's members
      // all read as "newly appeared" and flood toasts.
      _siblingState.clear();
      _toastBootstrapped = false;
      clearTimeout(timer);
      tick();
    });

    tick();
  }

  // Page-wide, independent of the strip: Stats and Settings have no strip but
  // still need an expired sign-in announced.
  function bootAuthBanner() {
    checkAuthHealth();
    setInterval(checkAuthHealth, 60000);
  }

  function boot() {
    bootRecentsStrip();
    bootAuthBanner();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
