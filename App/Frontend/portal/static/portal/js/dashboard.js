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

  // A "template" row pairs a Studio recipe (.json) with its rendered chart
  // (.html) in the same folder now; a "paper" row pairs its document (.json)
  // with its built report (.html) -- a row may carry either or both, tagged here.
  var SUFFIX = { csv: ".csv", template: ".json", paper: ".json" };
  var KIND_TAGS = {
    csv: { csv: "" },
    template: { json: "recipe", html: "chart" },
    paper: { json: "doc", html: "report" },
  };
  var FILE_KINDS = ["csv", "template", "paper"];
  var URLS = root ? {
    publish: root.getAttribute("data-publish-url"),
    describe: root.getAttribute("data-describe-url"),
    del: root.getAttribute("data-delete-url"),
    move: root.getAttribute("data-move-url"),
    fcreate: root.getAttribute("data-folder-create-url"),
    frename: root.getAttribute("data-folder-rename-url"),
    fdelete: root.getAttribute("data-folder-delete-url"),
    pdfImport: root.getAttribute("data-pdf-import-url"),
  } : {};
  function reload() { window.location.reload(); }
  function parseJSON(id) {
    var el = document.getElementById(id);
    try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; }
  }
  var USER_CHOICES = parseJSON("user-folder-choices-data") || {};
  // The user's own files as folder trees, keyed by kind (csv/template/paper) --
  // hoisted here (not local to initFileTrees) so the picker below, and Studio's
  // and Synthesize's own scripts (via window.PortalFileTrees), can all read it.
  var TREES = parseJSON("file-trees-data") || {};
  window.PortalFileTrees = TREES;

  // The public library is fetched once and shared by the public list and by every
  // "publish into which public folder?" prompt.
  var publicPromise = null;
  function loadPublic() {
    if (!publicPromise) {
      var lib = document.getElementById("public-library");
      publicPromise = lib
        ? fetch(lib.getAttribute("data-url"), { credentials: "same-origin" }).then(function (r) { return r.json(); })
        : Promise.resolve({});
    }
    return publicPromise;
  }
  function publicChoices(kind) {
    return loadPublic().then(function (d) { return (d.folder_choices || {})[kind] || [""]; });
  }

  // A modal that asks which folder to place an import/export in: pick an existing
  // folder or type a new (possibly nested) path. Resolves to the chosen path (""=root)
  // or null if cancelled.
  function pickFolder(choices, title) {
    return new Promise(function (resolve) {
      var overlay = document.createElement("div");
      overlay.className = "folder-modal-overlay";
      var opts = (choices && choices.length ? choices : [""]).map(function (c) {
        return '<option value="' + esc(c) + '">' + (c === "" ? "— root —" : esc(c)) + "</option>";
      }).join("");
      overlay.innerHTML = '<div class="folder-modal"><h4>' + esc(title) + "</h4>" +
        '<label>Existing folder</label><select class="fm-select">' + opts + "</select>" +
        '<label>…or a new folder path</label><input type="text" class="fm-new" placeholder="e.g. Figures/Temporal">' +
        '<div class="fm-actions"><button type="button" class="fm-cancel">Cancel</button>' +
        '<button type="button" class="fm-ok">Place here</button></div></div>';
      document.body.appendChild(overlay);
      function done(v) { overlay.remove(); resolve(v); }
      overlay.querySelector(".fm-cancel").addEventListener("click", function () { done(null); });
      overlay.addEventListener("click", function (e) { if (e.target === overlay) done(null); });
      overlay.querySelector(".fm-ok").addEventListener("click", function () {
        done((overlay.querySelector(".fm-new").value.trim()) || overlay.querySelector(".fm-select").value);
      });
      var nu = overlay.querySelector(".fm-new"); if (nu) nu.focus();
    });
  }

  function findByPath(node, path) {
    var files = node.files || [];
    for (var i = 0; i < files.length; i++) if (files[i].path === path) return files[i];
    var folders = node.folders || [];
    for (var j = 0; j < folders.length; j++) {
      var found = findByPath(folders[j], path);
      if (found) return found;
    }
    return null;
  }

  // A modal for picking ONE file out of one or more folder trees at once (e.g.
  // "Data" + "Charts" + "Reports") -- built for the four pickers that used to be
  // one giant flat <select> (View output, Export, Load template, Insert
  // visualization), all unwieldy once a workspace carries dozens of foldered
  // files. `groups`: [{ label, tree, filter(f), render(f) -> label, sub(f) ->
  // label }]. Resolves {group, file} or null if cancelled.
  function openGroupedPicker(title, groups) {
    return new Promise(function (resolve) {
      var overlay = document.createElement("div");
      overlay.className = "folder-modal-overlay";

      function fileRow(f, group) {
        var label = group.render ? group.render(f) : f.name;
        var sub = group.sub ? group.sub(f) : "";
        return '<li class="picker-row" data-path="' + esc(f.path) + '" data-group="' + esc(group.label) + '">' +
          esc(label) + (sub ? '<span class="picker-sub">' + esc(sub) + "</span>" : "") + "</li>";
      }
      function folderNode(node, group, isRoot) {
        var files = (node.files || []).filter(group.filter || function () { return true; });
        var inner = (node.folders || []).map(function (sf) { return folderNode(sf, group, false); }).join("") +
          files.map(function (f) { return fileRow(f, group); }).join("");
        if (!inner) return "";
        if (isRoot) return inner;
        return '<li class="tree-folder" data-path="' + esc(node.path) + '"><div class="folder-head">' +
          '<span class="folder-toggle">▾</span><span class="folder-name">' + esc(node.name) + "</span></div>" +
          '<ul class="file-list folder-body">' + inner + "</ul></li>";
      }
      var body = groups.map(function (g) {
        var inner = folderNode(g.tree || { folders: [], files: [], path: "" }, g, true);
        if (!inner) return "";
        return '<li class="tree-folder" data-path="__group:' + esc(g.label) + '"><div class="folder-head">' +
          '<span class="folder-toggle">▾</span><span class="folder-name">' + esc(g.label) + "</span></div>" +
          '<ul class="file-list folder-body">' + inner + "</ul></li>";
      }).join("");

      overlay.innerHTML = '<div class="folder-modal picker-modal"><h4>' + esc(title) + "</h4>" +
        '<input type="text" class="picker-filter" placeholder="Filter by name…">' +
        '<ul class="file-list picker-tree">' + (body || '<li class="placeholder">Nothing here yet.</li>') + "</ul>" +
        '<div class="fm-actions"><button type="button" class="fm-cancel">Cancel</button></div></div>';
      document.body.appendChild(overlay);

      function done(v) { overlay.remove(); resolve(v); }
      overlay.querySelector(".fm-cancel").addEventListener("click", function () { done(null); });
      overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) done(null); });
      overlay.addEventListener("click", function (e) {
        var t = e.target, folderEl = t.closest(".tree-folder");
        if (t.classList.contains("folder-toggle") || t.classList.contains("folder-name")) {
          if (folderEl) folderEl.classList.toggle("collapsed");
          return;
        }
        var row = t.closest(".picker-row");
        if (!row) return;
        var groupLabel = row.getAttribute("data-group");
        var group = groups.filter(function (g) { return g.label === groupLabel; })[0];
        var file = group && findByPath(group.tree, row.getAttribute("data-path"));
        if (file) done({ group: group, file: file });
      });
      var filterInput = overlay.querySelector(".picker-filter");
      filterInput.addEventListener("input", function () {
        var q = filterInput.value.trim().toLowerCase();
        overlay.querySelectorAll(".picker-row").forEach(function (row) {
          row.style.display = row.textContent.toLowerCase().indexOf(q) === -1 ? "none" : "";
        });
        if (q) overlay.querySelectorAll(".tree-folder").forEach(function (f) { f.classList.remove("collapsed"); });
      });
      filterInput.focus();
    });
  }
  window.openGroupedPicker = openGroupedPicker;

  // ---- The user's own files, as navigable folder trees ---------------------
  function initFileTrees() {
    if (!TREES) return;

    function kindTags(kind, f) {
      var labels = KIND_TAGS[kind] || {};
      return (f.kinds || []).map(function (k) {
        var label = labels[k];
        return label ? '<span class="kind-tag">' + esc(label) + "</span>" : "";
      }).join("");
    }
    function viewLink(kind, f) {
      if ((f.kinds || []).indexOf("html") === -1) return "";
      return '<a class="file-view" href="/outputs/html/' + encodeURIComponent(f.path) +
        '/" target="_blank" rel="noopener">View ↗</a>';
    }
    function fileRow(kind, f, actions) {
      var descClass = f.description ? "" : " empty";
      // "csv" has exactly one suffix, shown inline; "template"/"paper" may pair
      // two physical files under one row, so which ones exist is shown as tags.
      var suffix = kind === "csv" ? esc(SUFFIX.csv) : "";
      return '<li class="file-row" data-kind="' + kind + '" data-name="' + esc(f.path) + '">' +
        '<div class="file-main"><span class="file-name">' + esc(f.name) + suffix + "</span>" +
        kindTags(kind, f) +
        '<span class="file-actions">' + viewLink(kind, f) + actions + "</span></div>" +
        '<div class="file-desc' + descClass + '">' + esc(f.description || "") + "</div></li>";
    }
    function ownActions() {
      return '<button type="button" class="file-describe" title="Edit description">✎</button>' +
        '<button type="button" class="file-move" title="Move to a folder">Move</button>' +
        '<button type="button" class="file-publish" title="Publish to the public library">Publish</button>' +
        '<button type="button" class="file-delete" title="Delete">Delete</button>';
    }
    function folderNode(kind, node, isRoot) {
      var inner = node.folders.map(function (sf) { return folderNode(kind, sf, false); }).join("") +
        node.files.map(function (f) { return fileRow(kind, f, ownActions()); }).join("");
      if (isRoot) return inner || '<li class="placeholder">Nothing here yet.</li>';
      return '<li class="tree-folder" data-path="' + esc(node.path) + '">' +
        '<div class="folder-head"><span class="folder-toggle">▾</span> ' +
        '<span class="folder-name">' + esc(node.name) + "</span>" +
        '<span class="folder-actions">' +
          '<button type="button" class="folder-newsub" title="New subfolder">+ Folder</button>' +
          '<button type="button" class="folder-move" title="Move this folder">Move</button>' +
          '<button type="button" class="folder-publish" title="Publish this folder">Publish</button>' +
          '<button type="button" class="folder-rename" title="Rename">Rename</button>' +
          '<button type="button" class="folder-delete" title="Delete folder">Delete</button>' +
        "</span></div><ul class=\"file-list folder-body\">" + inner + "</ul></li>";
    }
    FILE_KINDS.forEach(function (kind) {
      var container = document.querySelector('.file-tree[data-kind="' + kind + '"]');
      if (!container) return;
      var tree = TREES[kind] || { folders: [], files: [], path: "" };
      container.innerHTML = '<ul class="file-list">' + folderNode(kind, tree, true) + "</ul>";
    });

    document.querySelectorAll(".file-tree").forEach(function (container) {
      var kind = container.getAttribute("data-kind");
      container.addEventListener("click", function (e) {
        var t = e.target, folderEl = t.closest(".tree-folder");
        if (t.classList.contains("folder-toggle") || t.classList.contains("folder-name")) {
          if (folderEl) folderEl.classList.toggle("collapsed");
          return;
        }
        var fpath = folderEl ? folderEl.getAttribute("data-path") : "";
        if (t.classList.contains("folder-newsub")) {
          var sub = prompt("New subfolder inside " + fpath + ":"); if (!sub) return;
          post(URLS.fcreate, { kind: kind, parent: fpath, name: sub }).then(reload); return;
        }
        if (t.classList.contains("folder-rename")) {
          var nn = prompt("Rename folder:", folderEl.querySelector(".folder-name").textContent.trim()); if (!nn) return;
          post(URLS.frename, { kind: kind, path: fpath, name: nn }).then(reload); return;
        }
        if (t.classList.contains("folder-delete")) {
          if (!confirm("Delete folder “" + fpath + "” and everything in it?")) return;
          post(URLS.fdelete, { kind: kind, path: fpath }).then(reload); return;
        }
        if (t.classList.contains("folder-move")) {
          pickFolder(USER_CHOICES[kind], "Move folder into:").then(function (dest) {
            if (dest === null) return;
            post(URLS.move, { kind: kind, path: fpath, is_folder: 1, folder: dest }).then(reload);
          }); return;
        }
        if (t.classList.contains("folder-publish")) {
          publicChoices(kind).then(function (pc) {
            return pickFolder(pc, "Publish folder to which public folder?").then(function (dest) {
              if (dest === null) return;
              post(URLS.publish, { kind: kind, path: fpath, is_folder: 1, folder: dest }).then(reload);
            });
          }); return;
        }
        var row = t.closest(".file-row"); if (!row) return;
        var name = row.getAttribute("data-name");
        if (t.classList.contains("file-describe")) {
          var descEl = row.querySelector(".file-desc");
          var next = prompt("Description for " + name + ":", descEl ? descEl.textContent.trim() : "");
          if (next === null) return;
          post(URLS.describe, { kind: kind, name: name, description: next }).then(reload); return;
        }
        if (t.classList.contains("file-delete")) {
          if (!confirm("Delete " + name + "? This cannot be undone.")) return;
          post(URLS.del, { kind: kind, name: name }).then(reload); return;
        }
        if (t.classList.contains("file-move")) {
          pickFolder(USER_CHOICES[kind], "Move file into:").then(function (dest) {
            if (dest === null) return;
            post(URLS.move, { kind: kind, name: name, folder: dest }).then(reload);
          }); return;
        }
        if (t.classList.contains("file-publish")) {
          publicChoices(kind).then(function (pc) {
            return pickFolder(pc, "Publish to which public folder?").then(function (dest) {
              if (dest === null) return;
              post(URLS.publish, { kind: kind, name: name, folder: dest }).then(reload);
            });
          }); return;
        }
      });
    });

    document.querySelectorAll(".folder-new-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var kind = btn.getAttribute("data-kind");
        var name = prompt("New folder name:"); if (!name) return;
        post(URLS.fcreate, { kind: kind, parent: "", name: name }).then(reload);
      });
    });
  }

  // ---- Public library: navigable trees + folder-aware pull -----------------
  function initPublicLibrary() {
    var lib = document.getElementById("public-library");
    if (!lib) return;
    var IMPORT_URL = lib.getAttribute("data-import-url");
    var LABELS = { csv: "Data", template: "Templates", paper: "Papers" };

    function fileRow(kind, f) {
      var desc = f.description ? '<div class="file-desc">' + esc(f.description) + "</div>" : "";
      var suffix = kind === "csv" ? esc(SUFFIX.csv) : "";
      var labels = KIND_TAGS[kind] || {};
      var tags = (f.kinds || []).map(function (k) {
        var label = labels[k];
        return label ? '<span class="kind-tag">' + esc(label) + "</span>" : "";
      }).join("");
      return '<li class="file-row" data-kind="' + kind + '" data-name="' + esc(f.path) + '">' +
        '<div class="file-main"><span class="file-name">' + esc(f.name) + suffix + "</span>" + tags +
        '<button type="button" class="public-pull">Pull</button></div>' + desc + "</li>";
    }
    function folderNode(kind, node, isRoot) {
      var inner = node.folders.map(function (sf) { return folderNode(kind, sf, false); }).join("") +
        node.files.map(function (f) { return fileRow(kind, f); }).join("");
      if (isRoot) return inner;
      return '<li class="tree-folder collapsed" data-path="' + esc(node.path) + '">' +
        '<div class="folder-head"><span class="folder-toggle">▾</span> ' +
        '<span class="folder-name">' + esc(node.name) + "</span>" +
        '<button type="button" class="public-pull-folder" title="Pull whole folder">Pull folder</button>' +
        '</div><ul class="file-list folder-body">' + inner + "</ul></li>";
    }
    function group(kind, tree) {
      if (!tree || (!tree.folders.length && !tree.files.length)) return "";
      return "<h4>" + esc(LABELS[kind]) + "</h4><ul class=\"file-list\">" +
        folderNode(kind, tree, true) + "</ul>";
    }
    function pdfGroup(items) {
      if (!items || !items.length) return "";
      var rows = items.map(function (it) {
        var desc = it.description ? '<div class="file-desc">' + esc(it.description) + "</div>" : "";
        return '<li class="file-row" data-kind="pdf" data-name="' + esc(it.name) + '">' +
          '<div class="file-main"><span class="file-name">' + esc(it.name) +
          ' <span class="file-count">(' + esc(it.count) + " PDFs)</span></span>" +
          '<button type="button" class="public-pull">Pull</button></div>' + desc + "</li>";
      }).join("");
      return "<h4>PDF collections</h4><ul class=\"file-list\">" + rows + "</ul>";
    }

    loadPublic().then(function (d) {
      var trees = d.trees || {};
      var html = FILE_KINDS.map(function (k) { return group(k, trees[k]); }).join("") + pdfGroup(d.pdf);
      lib.innerHTML = html || '<p class="placeholder">The public library is empty.</p>';
    }).catch(function () { lib.innerHTML = '<p class="placeholder">Could not load the public library.</p>'; });

    lib.addEventListener("click", function (e) {
      var t = e.target, folderEl = t.closest(".tree-folder");
      if (t.classList.contains("folder-toggle") || t.classList.contains("folder-name")) {
        if (folderEl) folderEl.classList.toggle("collapsed"); return;
      }
      if (t.classList.contains("public-pull-folder")) {
        // the folder's kind = the data-kind of any file row inside it
        var anyRow = folderEl.querySelector(".file-row");
        var fkind = anyRow ? anyRow.getAttribute("data-kind") : null;
        if (!fkind) return;
        pickFolder(USER_CHOICES[fkind], "Import folder into which of your folders?").then(function (dest) {
          if (dest === null) return;
          post(IMPORT_URL, { kind: fkind, path: folderEl.getAttribute("data-path"), is_folder: 1, folder: dest }).then(reload);
        });
        return;
      }
      if (!t.classList.contains("public-pull")) return;
      var row = t.closest(".file-row");
      var rkind = row.getAttribute("data-kind"), rname = row.getAttribute("data-name");
      if (rkind === "pdf") { post(URLS.pdfImport, { name: rname }).then(reload); return; }
      pickFolder(USER_CHOICES[rkind], "Import into which of your folders?").then(function (dest) {
        if (dest === null) return;
        post(IMPORT_URL, { kind: rkind, name: rname, folder: dest }).then(reload);
      });
    });
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
    var btn = document.getElementById("output-viewer-picker-btn");
    if (!btn) return;
    var current = document.getElementById("output-viewer-current");
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

    btn.addEventListener("click", function () {
      openGroupedPicker("View an output", [
        { label: "Data", tree: TREES.csv, resultKind: "csv",
          render: function (f) { return f.name + ".csv"; } },
        { label: "Charts", tree: TREES.template, resultKind: "html",
          filter: function (f) { return (f.kinds || []).indexOf("html") !== -1; },
          render: function (f) { return f.name + ".html"; } },
        { label: "Reports", tree: TREES.paper, resultKind: "html",
          filter: function (f) { return (f.kinds || []).indexOf("html") !== -1; },
          render: function (f) { return f.name + ".html"; } },
      ]).then(function (picked) {
        if (!picked) return;
        current.textContent = picked.file.name + (picked.group.resultKind === "csv" ? ".csv" : ".html");
        render(picked.group.resultKind, picked.file.name);
      });
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

  // ---- Export: download a chosen file ---------------------------------------
  function initExport() {
    var btn = document.getElementById("export-picker-btn");
    if (!btn) return;
    var current = document.getElementById("export-current");

    function exportUrl(urlKind, name, ext) {
      var url = "/files/export/" + encodeURIComponent(urlKind) + "/" + encodeURIComponent(name) + "/";
      return ext ? url + "?ext=" + encodeURIComponent(ext) : url;
    }

    btn.addEventListener("click", function () {
      openGroupedPicker("Export", [
        { label: "Data", tree: TREES.csv, urlKind: "csv", suffix: ".csv",
          render: function (f) { return f.name + ".csv"; } },
        { label: "Recipes", tree: TREES.template, urlKind: "template", suffix: ".json",
          filter: function (f) { return (f.kinds || []).indexOf("json") !== -1; },
          render: function (f) { return f.name + ".json"; } },
        { label: "Charts", tree: TREES.template, urlKind: "template", ext: "html", suffix: ".html",
          filter: function (f) { return (f.kinds || []).indexOf("html") !== -1; },
          render: function (f) { return f.name + ".html"; } },
        { label: "Paper docs", tree: TREES.paper, urlKind: "paper", suffix: ".json",
          filter: function (f) { return (f.kinds || []).indexOf("json") !== -1; },
          render: function (f) { return f.name + ".json"; } },
        { label: "Reports", tree: TREES.paper, urlKind: "paper", ext: "html", suffix: ".html",
          filter: function (f) { return (f.kinds || []).indexOf("html") !== -1; },
          render: function (f) { return f.name + ".html"; } },
      ]).then(function (picked) {
        if (!picked) return;
        var g = picked.group;
        current.textContent = picked.file.name + g.suffix;
        window.location.href = exportUrl(g.urlKind, picked.file.name, g.ext);
      });
    });
  }

  safe(initFileTrees);
  safe(initPublicLibrary);
  safe(initTaskForm);
  safe(initOutputViewer);
  safe(initTaskProgress);
  safe(initExport);
})();
