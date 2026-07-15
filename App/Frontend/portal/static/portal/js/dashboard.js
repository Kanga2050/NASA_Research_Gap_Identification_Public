/* Dashboard tab behaviour, lifted out of workspace.html (which previously carried
 * six inline <script> blocks and defined the same post() helper twice). Config
 * that used to be interpolated by Django — the CSRF token and a few {% url %}s —
 * now rides on #dashboard-root's data-* attributes so this file can be a cached,
 * static asset. Each concern is its own init function wrapped in safe(), so one
 * failing section can't stop the others (the old separate <script> tags gave
 * that isolation for free). */
(function () {
  "use strict";

  var root = document.getElementById("dashboard-root");
  var CSRF = root ? root.getAttribute("data-csrf") : "";

  function post(url, params) {
    var body = Object.keys(params).map(function (k) {
      return encodeURIComponent(k) + "=" + encodeURIComponent(params[k]);
    }).join("&");
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": CSRF, "Content-Type": "application/x-www-form-urlencoded" },
      credentials: "same-origin",
      body: body,
    });
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function safe(fn) {
    try { fn(); } catch (e) { if (window.console) console.error(e); }
  }

  // ---- Publish / describe / delete on the user's own files -----------------
  function initOwnFiles() {
    var PUBLISH_URL = root && root.getAttribute("data-publish-url");
    var DESCRIBE_URL = root && root.getAttribute("data-describe-url");
    var DELETE_URL = root && root.getAttribute("data-delete-url");
    document.querySelectorAll(".sidebar .file-list").forEach(function (list) {
      if (list.closest("#public-library")) return;
      list.addEventListener("click", function (e) {
        var row = e.target.closest(".file-row");
        if (!row) return;
        var kind = row.getAttribute("data-kind");
        var name = row.getAttribute("data-name");
        if (e.target.classList.contains("file-publish")) {
          if (!confirm("Publish " + name + " to the shared public library?")) return;
          post(PUBLISH_URL, { kind: kind, name: name }).then(function () { window.location.reload(); });
        } else if (e.target.classList.contains("file-describe")) {
          var descEl = row.querySelector(".file-desc");
          var current = descEl ? descEl.textContent.trim() : "";
          var next = prompt("Description for " + name + ":", current);
          if (next === null) return;
          post(DESCRIBE_URL, { kind: kind, name: name, description: next }).then(function () { window.location.reload(); });
        } else if (e.target.classList.contains("file-delete")) {
          if (!confirm("Delete " + name + "? This cannot be undone.")) return;
          post(DELETE_URL, { kind: kind, name: name }).then(function () { window.location.reload(); });
        }
      });
    });
  }

  // ---- Public library: list + pull -----------------------------------------
  function initPublicLibrary() {
    var lib = document.getElementById("public-library");
    if (!lib) return;
    var IMPORT_URL = lib.getAttribute("data-import-url");
    var SUFFIX = { csv: ".csv", html: ".html", template: ".json", paper: ".json" };
    var LABELS = { csv: "Data", html: "Visualizations", template: "Templates", paper: "Papers" };
    function group(kind, items) {
      if (!items.length) return "";
      var rows = items.map(function (it) {
        var desc = it.description ? '<div class="file-desc">' + esc(it.description) + "</div>" : "";
        return '<li class="file-row" data-kind="' + kind + '" data-name="' + esc(it.name) + '">' +
          '<div class="file-main"><span class="file-name">' + esc(it.name) + esc(SUFFIX[kind]) + "</span>" +
          '<button type="button" class="public-pull">Pull</button></div>' + desc + "</li>";
      }).join("");
      return "<h4>" + esc(LABELS[kind]) + "</h4><ul class=\"file-list\">" + rows + "</ul>";
    }
    fetch(lib.getAttribute("data-url"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var html = ["csv", "html", "template", "paper"].map(function (k) { return group(k, d[k] || []); }).join("");
        lib.innerHTML = html || '<p class="placeholder">The public library is empty.</p>';
      })
      .catch(function () { lib.innerHTML = '<p class="placeholder">Could not load the public library.</p>'; });
    lib.addEventListener("click", function (e) {
      if (!e.target.classList.contains("public-pull")) return;
      var row = e.target.closest(".file-row");
      post(IMPORT_URL, { kind: row.getAttribute("data-kind"), name: row.getAttribute("data-name") })
        .then(function () { window.location.reload(); });
    });
  }

  // ---- PDF collections: list / delete / pull -------------------------------
  function initPdfCollections() {
    var box = document.getElementById("pdf-collections");
    if (!box) return;
    function row(folder, action, label) {
      var li = document.createElement("li");
      li.className = "file-row";
      var main = document.createElement("div");
      main.className = "file-main";
      var name = document.createElement("span");
      name.className = "file-name";
      name.textContent = folder.name + " (" + folder.count + " PDFs)";
      var acts = document.createElement("span");
      acts.className = "file-actions";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.addEventListener("click", action);
      acts.appendChild(btn);
      main.appendChild(name);
      main.appendChild(acts);
      li.appendChild(main);
      return li;
    }
    function render(data) {
      box.innerHTML = "";
      var yours = document.createElement("h3");
      yours.textContent = "Your collections";
      box.appendChild(yours);
      var ul = document.createElement("ul");
      ul.className = "file-list";
      (data.user || []).forEach(function (f) {
        ul.appendChild(row(f, function () {
          if (!confirm("Delete PDF collection '" + f.name + "'?")) return;
          post(box.getAttribute("data-delete-url"), { name: f.name }).then(function () { window.location.reload(); });
        }, "Delete"));
      });
      if (!(data.user || []).length) {
        var none = document.createElement("li");
        none.className = "placeholder";
        none.textContent = "No collections yet. Upload PDFs above.";
        ul.appendChild(none);
      }
      box.appendChild(ul);

      var pub = document.createElement("h3");
      pub.textContent = "Public library";
      box.appendChild(pub);
      var ul2 = document.createElement("ul");
      ul2.className = "file-list";
      (data.public || []).forEach(function (f) {
        ul2.appendChild(row(f, function () {
          post(box.getAttribute("data-import-url"), { name: f.name }).then(function () { window.location.reload(); });
        }, "Pull"));
      });
      if (!(data.public || []).length) {
        var none2 = document.createElement("li");
        none2.className = "placeholder";
        none2.textContent = "The public PDF library is empty.";
        ul2.appendChild(none2);
      }
      box.appendChild(ul2);
    }
    fetch(box.getAttribute("data-url"), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () { box.innerHTML = '<p class="placeholder">Could not load PDF collections.</p>'; });
  }

  // ---- "Queue a task" form: field visibility + CSV column loading ----------
  function initTaskForm() {
    // Which fields each action shows, which of them are CSV-column dropdowns, and
    // which one picks its source CSV -- all derived from the backend function
    // registry (see App/Backend/registry.py), so this page can never offer an
    // argument the function does not take.
    var specEl = document.getElementById("task-action-spec");
    if (!specEl) return;
    var ACTION_SPEC = JSON.parse(specEl.textContent);
    var EMPTY_SPEC = { fields: [], columnFields: [], csvSource: null };
    function specFor(action) { return ACTION_SPEC[action] || EMPTY_SPEC; }

    var form = document.getElementById("task-form");
    if (!form) return;
    var actionSelect = form.querySelector("[data-field='action'] select, [data-field='action'] input");
    var fieldRows = form.querySelectorAll("[data-field]");
    var csvSelect = form.querySelector("[data-role='csv-select']");
    var csvText = form.querySelector("[data-role='csv-text']");
    var sourceCsvSelect = form.querySelector("[data-role='source-csv-select']");
    var columnSelects = form.querySelectorAll("[data-role='column-select']");

    function updateVisibility() {
      var visible = specFor(actionSelect.value).fields;
      fieldRows.forEach(function (row) {
        var name = row.getAttribute("data-field");
        if (name === "action" || visible.indexOf(name) !== -1) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    }

    function updateCsvNameMode() {
      // Actions that produce a brand-new CSV (no csvSource -- e.g. openalex_scraper,
      // chunk_pdfs) name their output via the free-text box; everything else picks
      // an existing CSV from the dropdown.
      var producesNewCsv = !specFor(actionSelect.value).csvSource;
      csvSelect.disabled = producesNewCsv;
      csvSelect.style.display = producesNewCsv ? "none" : "";
      csvText.disabled = !producesNewCsv;
      csvText.style.display = producesNewCsv ? "" : "none";
    }

    function populateColumns(columns) {
      var relevant = specFor(actionSelect.value).columnFields;
      columnSelects.forEach(function (select) {
        var fieldRow = select.closest("[data-field]");
        if (relevant.indexOf(fieldRow.getAttribute("data-field")) === -1) {
          return;
        }
        var initial = select.getAttribute("data-initial");
        var previous = select.value;
        select.innerHTML = "";
        if (!columns.length) {
          var placeholder = document.createElement("option");
          placeholder.value = "";
          placeholder.textContent = "No columns available";
          select.appendChild(placeholder);
          return;
        }
        columns.forEach(function (col) {
          var opt = document.createElement("option");
          opt.value = col;
          opt.textContent = col;
          select.appendChild(opt);
        });
        if (columns.indexOf(previous) !== -1) {
          select.value = previous;
        } else if (columns.indexOf(initial) !== -1) {
          select.value = initial;
        }
      });
    }

    function refreshColumns() {
      var source = specFor(actionSelect.value).csvSource;
      var csvName = source === "csv_name" ? csvSelect.value : source === "source_csv" ? sourceCsvSelect.value : null;
      if (!csvName) {
        populateColumns([]);
        return;
      }
      fetch("/csvs/" + encodeURIComponent(csvName) + "/columns/")
        .then(function (r) { return r.json(); })
        .then(function (data) { populateColumns(data.columns || []); })
        .catch(function () { populateColumns([]); });
    }

    function handleActionChange() {
      updateVisibility();
      updateCsvNameMode();
      refreshColumns();
    }

    // PDF-collection multi-select -> hidden comma-separated "folders" input.
    var pdfFoldersSelect = form.querySelector("[data-role='pdf-folders-select']");
    var pdfFoldersValue = form.querySelector("[data-role='pdf-folders-value']");
    function syncPdfFolders() {
      if (!pdfFoldersSelect || !pdfFoldersValue) return;
      pdfFoldersValue.value = Array.prototype.filter
        .call(pdfFoldersSelect.options, function (o) { return o.selected; })
        .map(function (o) { return o.value; })
        .join(",");
    }
    if (pdfFoldersSelect) pdfFoldersSelect.addEventListener("change", syncPdfFolders);
    form.addEventListener("submit", syncPdfFolders);

    actionSelect.addEventListener("change", handleActionChange);
    if (csvSelect) csvSelect.addEventListener("change", refreshColumns);
    if (sourceCsvSelect) sourceCsvSelect.addEventListener("change", refreshColumns);

    handleActionChange();
  }

  // ---- "View an output" picker: CSV table / HTML iframe preview ------------
  function initOutputViewer() {
    var select = document.getElementById("output-viewer-select");
    if (!select) return;
    var container = document.getElementById("output-viewer");

    function renderCsv(name, data) {
      if (data.missing) {
        container.innerHTML = '<p class="placeholder">' + esc(name) + '.csv was not found.</p>';
        return;
      }
      var html = '<h3>' + esc(name) + '.csv</h3>';
      html += '<p class="placeholder">Showing first ' + (data.preview_row_count || 0) + ' rows</p>';
      html += '<div class="output-table-wrap"><table class="output-table"><thead><tr>';
      (data.columns || []).forEach(function (col) { html += '<th>' + esc(col) + '</th>'; });
      html += '</tr></thead><tbody>';
      (data.rows || []).forEach(function (row) {
        html += '<tr>';
        row.forEach(function (cell) { html += '<td title="' + esc(cell) + '">' + esc(cell) + '</td>'; });
        html += '</tr>';
      });
      html += '</tbody></table></div>';
      container.innerHTML = html;
    }

    function render(kind, name) {
      if (!name) { container.style.display = "none"; container.innerHTML = ""; return; }
      container.style.display = "";
      if (kind === "html") {
        container.innerHTML = '<h3>' + esc(name) + '.html</h3>';
        var iframe = document.createElement("iframe");
        iframe.src = "/outputs/html/" + encodeURIComponent(name) + "/";
        container.appendChild(iframe);
        return;
      }
      container.innerHTML = '<p class="placeholder">Loading&hellip;</p>';
      fetch("/outputs/preview/" + encodeURIComponent(kind) + "/" + encodeURIComponent(name) + "/")
        .then(function (r) { return r.json(); })
        .then(function (data) { renderCsv(name, data); })
        .catch(function () { container.innerHTML = '<p class="placeholder">Could not load preview.</p>'; });
    }

    select.addEventListener("change", function () {
      var val = select.value;
      if (!val) { render(null, null); return; }
      var sep = val.indexOf(":");
      render(val.slice(0, sep), val.slice(sep + 1));
    });
  }

  // ---- Live progress polling for a queued/working latest task --------------
  function initTaskProgress() {
    var el = document.getElementById("task-progress");
    if (!el) return;
    var printEl = document.getElementById("task-progress-print");
    var taskId = el.getAttribute("data-task-id");
    var lastPrint = null;

    function poll() {
      fetch("/tasks/" + taskId + "/status/")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            setTimeout(poll, 2000);
            return;
          }
          if (data.latest_print && data.latest_print !== lastPrint) {
            lastPrint = data.latest_print;
            printEl.textContent = lastPrint;
          }
          if (data.status === "completed" || data.status === "failed" || data.status === "cancelled") {
            window.location.reload();
            return;
          }
          setTimeout(poll, 1200);
        })
        .catch(function () { setTimeout(poll, 2000); });
    }

    poll();
  }

  // ---- Export form: download the selected file -----------------------------
  function initExport() {
    var form = document.getElementById("export-form");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var url = document.getElementById("export-select").value;
      if (url) window.location.href = url;
    });
  }

  safe(initOwnFiles);
  safe(initPublicLibrary);
  safe(initPdfCollections);
  safe(initTaskForm);
  safe(initOutputViewer);
  safe(initTaskProgress);
  safe(initExport);
})();
