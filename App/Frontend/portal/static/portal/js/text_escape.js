/* Shared HTML-escaping helpers used by every page script that builds HTML strings
 * from server data (dashboard.js, studio.js, synthesize.js, tasks_live.js), so the
 * escaping rules can never drift between them the way `esc()`/`escText()` had:
 * some escaped quotes, some didn't, and only synthesize.js had an attribute-safe
 * variant. Load this before any script that calls escText/escAttr/esc. */
(function (global) {
  function escText(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function escAttr(s) {
    return escText(s).replace(/"/g, "&quot;");
  }

  global.escText = escText;
  global.escAttr = escAttr;
  // Historical name used by dashboard.js/studio.js/tasks_live.js; was always
  // equivalent to escAttr (it escaped quotes too).
  global.esc = escAttr;
})(window);
