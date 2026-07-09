/* Shared task feed.
 *
 * Polls GET /tasks/feed/ for the signed-in user's recent tasks (newest first,
 * same list the Dashboard renders server-side at page load) and uses that one
 * response to refresh two different views of the same data:
 *   - #recent-tasks-list (Dashboard "Recent tasks"): every task, as-is.
 *   - #active-tasks-list (Studio "Active tasks"): just the queued/working ones.
 * Because both panels are mounted on the same page and read the same fetch,
 * a task queued from either tab is reflected identically, live, on both.
 */
(function () {
  var recentList = document.getElementById("recent-tasks-list");
  var activeList = document.getElementById("active-tasks-list");
  var activeCount = document.getElementById("active-tasks-count");
  if (!recentList && !activeList) return;
  var POLL_MS = 1500;
  var lastJson = null;

  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function renderRecent(tasks) {
    if (!recentList) return;
    if (!tasks.length) {
      recentList.innerHTML = '<p class="placeholder">No tasks yet.</p>';
      return;
    }
    recentList.innerHTML = tasks.map(function (t) {
      return '<div class="task-row">' +
        "<span>" + esc(t.createdAt) + " &middot; " + esc(t.function_name) + "</span>" +
        '<span class="status-pill ' + esc(t.status) + '">' + esc(t.status) + "</span>" +
        "</div>";
    }).join("");
  }

  function renderActive(tasks) {
    if (!activeList) return;
    var active = tasks.filter(function (t) { return t.status === "queued" || t.status === "working"; });
    if (activeCount) activeCount.textContent = active.length ? String(active.length) : "";
    if (!active.length) {
      activeList.innerHTML = '<p class="placeholder">No active tasks right now.</p>';
      return;
    }
    activeList.innerHTML = active.map(function (t) {
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
    fetch("/tasks/feed/", { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { tasks: [] }; })
      .then(function (d) {
        var tasks = d.tasks || [];
        var signature = JSON.stringify(tasks);
        if (signature !== lastJson) {
          lastJson = signature;
          renderRecent(tasks);
          renderActive(tasks);
        }
      })
      .catch(function () {})
      .then(function () { setTimeout(poll, POLL_MS); });
  }

  poll();
})();
