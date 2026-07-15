/* Switches between the Dashboard and Studio panels client-side (no page reload)
 * so in-progress state on either tab (form drafts, the Drawflow canvas, agent
 * chat scroll position) survives switching. Falls back to normal navigation via
 * each tab's href if JS never runs. Also drives the title-bar "Getting started"
 * panel. */
(function () {
  var tabs = document.querySelectorAll(".tabbar .tab[data-tab]");
  var panels = document.querySelectorAll(".tab-panel[data-tab]");

  function activate(name, push) {
    tabs.forEach(function (t) { t.classList.toggle("active", t.getAttribute("data-tab") === name); });
    panels.forEach(function (p) { p.classList.toggle("active", p.getAttribute("data-tab") === name); });
    if (push) {
      var link = document.querySelector('.tabbar .tab[data-tab="' + name + '"]');
      if (link) history.pushState({ tab: name }, "", link.getAttribute("href"));
    }
  }

  if (tabs.length && panels.length) {
    tabs.forEach(function (t) {
      t.addEventListener("click", function (e) {
        e.preventDefault();
        activate(t.getAttribute("data-tab"), true);
      });
    });

    window.addEventListener("popstate", function (e) {
      var name = e.state && e.state.tab;
      if (!name) {
        var active = document.querySelector(".tabbar .tab.active[data-tab]");
        name = active ? active.getAttribute("data-tab") : null;
      }
      if (name) activate(name, false);
    });

    var initial = document.querySelector(".tabbar .tab.active[data-tab]");
    if (initial) history.replaceState({ tab: initial.getAttribute("data-tab") }, "", location.href);
  }

  // ---------------------------------------------------- getting-started panel
  var infoBtn = document.getElementById("site-info-btn");
  var overlay = document.getElementById("getting-started-overlay");
  if (infoBtn && overlay) {
    var closeBtn = document.getElementById("getting-started-close");
    var panel = document.getElementById("getting-started-panel");

    // Keep Tab focus inside the open dialog (a modal shouldn't let keyboard
    // users tab out to the page behind the backdrop).
    function trapFocus(e) {
      if (e.key !== "Tab") return;
      var f = panel.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }

    function open() {
      overlay.hidden = false;
      document.body.classList.add("modal-open");
      infoBtn.setAttribute("aria-expanded", "true");
      document.addEventListener("keydown", trapFocus);
      closeBtn.focus();
    }
    function close() {
      overlay.hidden = true;
      document.body.classList.remove("modal-open");
      infoBtn.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", trapFocus);
      infoBtn.focus();
    }

    infoBtn.addEventListener("click", open);
    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !overlay.hidden) close();
    });
  }

  // ------------------------------------------------ info-icon accessibility
  // The little "i" help chips carry their text in a CSS-only `data-tip`
  // tooltip, which assistive tech never sees. Mirror it into an aria-label so
  // screen-reader users get the same hint instead of a bare "i".
  document.querySelectorAll(".info-icon[data-tip]").forEach(function (el) {
    if (!el.getAttribute("aria-label")) el.setAttribute("aria-label", el.getAttribute("data-tip"));
    if (!el.getAttribute("role")) el.setAttribute("role", "note");
  });
})();
