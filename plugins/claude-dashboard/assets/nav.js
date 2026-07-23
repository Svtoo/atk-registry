// App-nav dropdown menu: open/close, dismiss on outside-click or Escape.
// Which entry is current is decided by the server (serve.py SECTIONS) and comes
// down already marked, so nothing here infers it from the URL. The theme toggle
// is injected into the panel's [data-theme-slot] by dashboard.js.
(function () {
  "use strict";

  function wireMenu(menu) {
    var trigger = menu.querySelector(".appmenu-trigger");
    var panel = menu.querySelector(".appmenu-panel");
    if (!trigger || !panel) return;

    function close() {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
    function open() {
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
    }
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      panel.hidden ? open() : close();
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function init() {
    document.querySelectorAll("[data-appmenu]").forEach(wireMenu);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
