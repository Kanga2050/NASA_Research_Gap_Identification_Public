/* Shared live task panel.
 *
 * Polls /tasks/active/ for the signed-in user's ongoing (working) + scheduled
 * (queued) tasks and renders them. Because this lives in base.html it appears on
 * both the Dashboard and Studio tabs, so a task queued on one tab shows up live
 * on the other — keeping the two views in sync without a manual reload.
 */
(function () {
  var root = document.getElementById("active-tasks");
  if (!root) return;
  var list = document.getElementById("active-tasks-list");
  var count = document.getElementById("active-tasks-count");
  var POLL_MS = 1500;
  var lastJson = null;

  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function render(tasks) {
    if (!tasks.length) {
      root.style.display = "none";
      list.innerHTML = "";
      if (count) count.textContent = "";
      return;
    }
    root.style.display = "";
    if (count) count.textContent = String(tasks.length);
    list.innerHTML = tasks.map(function (t) {
      var print = t.latest_print
        ? '<span class="active-task-print" title="' + esc(t.latest_print) + '">' + esc(t.latest_print) + "</span>"
        : "";
      return '<div class="active-task-row">' +
        '<span class="active-task-fn">' + esc(t.function_name) + "</span>" +
        '<span class="status-pill ' + esc(t.status) + '">' + esc(t.status) + "</span>" +
        print + "</div>";
    }).join("");
  }

  function poll() {
    fetch("/tasks/active/", { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { tasks: [] }; })
      .then(function (d) {
        var tasks = d.tasks || [];
        var signature = JSON.stringify(tasks);
        if (signature !== lastJson) { lastJson = signature; render(tasks); }
      })
      .catch(function () {})
      .then(function () { setTimeout(poll, POLL_MS); });
  }

  poll();
})();
