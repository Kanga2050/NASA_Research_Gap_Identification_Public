/* Studio — visual scripting node editor (Drawflow).
 *
 * Nodes are wired through a single "table" port that carries a CSV/dataframe and
 * defines execution dependency. Column inputs inside each node are typed
 * comboboxes whose suggestions are the *projected* columns available at that
 * point in the graph (source CSV columns + columns added by upstream annotation
 * nodes), filtered to each port's accepted wire type (text/number/date/embedding).
 * Run compiles the graph and POSTs it; the server topologically sorts and queues
 * every task in dependency order (per-user FIFO execution preserves that order).
 */
(function () {
  var root = document.getElementById("studio");
  if (!root || typeof Drawflow === "undefined") return;

  var MANIFEST = JSON.parse(document.getElementById("studio-manifest").textContent);
  var CSV_NAMES = JSON.parse(document.getElementById("studio-csvs").textContent);
  var CSRF = root.getAttribute("data-csrf");
  var COLUMNS_URL = root.getAttribute("data-columns-url");
  var RUN_URL = root.getAttribute("data-run-url");
  var STATUS_URL = root.getAttribute("data-status-url");
  var HTML_URL = root.getAttribute("data-html-url");

  var columnCache = {}; // csvName -> [{name, type}]

  var container = document.getElementById("drawflow");
  var editor = new Drawflow(container);
  editor.reroute = true;
  editor.start();

  // ---------------------------------------------------------------- helpers
  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function mergeCols(a, b) {
    var seen = {}, out = [];
    a.concat(b).forEach(function (c) {
      if (c && c.name && !seen[c.name]) { seen[c.name] = 1; out.push(c); }
    });
    return out;
  }

  function ensureColumns(csv) {
    if (!csv || columnCache[csv]) return Promise.resolve();
    return fetch(COLUMNS_URL.replace("__NAME__", encodeURIComponent(csv)))
      .then(function (r) { return r.json(); })
      .then(function (d) { columnCache[csv] = d.typed || []; })
      .catch(function () { columnCache[csv] = []; });
  }

  function allNodeIds() {
    var data = editor.export().drawflow.Home.data;
    return Object.keys(data);
  }

  // ------------------------------------------------ projected column typing
  // Columns a node *emits* to its downstream table.
  function nodeOutputColumns(id, visited) {
    visited = visited || {};
    if (visited[id]) return [];
    visited[id] = 1;
    var node = editor.getNodeFromId(id);
    if (!node) return [];
    var entry = MANIFEST.nodes[node.name];
    var data = node.data || {};
    var fields = data.fields || {};

    if (node.name === "__csv__") return (columnCache[data.csv] || []).slice();

    var base = [];
    var inCons = (node.inputs.input_1 && node.inputs.input_1.connections) || [];
    inCons.forEach(function (c) { base = mergeCols(base, nodeOutputColumns(c.node, visited)); });
    if (!entry) return base;
    if (entry.projects === "replace") base = [];

    var added = [];
    if (entry.output && entry.output.kind === "column") {
      var nm = fields[entry.output.param] || entry.output.default;
      if (nm) added.push({ name: nm, type: entry.output.type || "text" });
    }
    if (node.name === "arithmetic" && (fields.new_column_name || "result")) {
      added.push({ name: fields.new_column_name || "result", type: "number" });
    }
    return mergeCols(base, added);
  }

  // Columns available *into* a node (its input table's emitted columns).
  function inputColumns(id) {
    var node = editor.getNodeFromId(id);
    if (!node) return [];
    var cols = [];
    var inCons = (node.inputs.input_1 && node.inputs.input_1.connections) || [];
    inCons.forEach(function (c) { cols = mergeCols(cols, nodeOutputColumns(c.node, {})); });
    return cols;
  }

  function populateNodeColumns(id) {
    var node = editor.getNodeFromId(id);
    if (!node) return;
    var entry = MANIFEST.nodes[node.name];
    if (!entry || !entry.columns.length) return;
    var avail = inputColumns(id);
    entry.columns.forEach(function (col) {
      var dl = document.getElementById("dl-" + id + "-" + col.param);
      if (!dl) return;
      dl.innerHTML = "";
      avail.filter(function (c) { return col.accepts.indexOf(c.type) !== -1; })
        .forEach(function (c) {
          var o = document.createElement("option");
          o.value = c.name;
          o.label = c.type;
          dl.appendChild(o);
        });
    });
  }

  function refreshAllColumns() {
    allNodeIds().forEach(populateNodeColumns);
  }

  // ----------------------------------------------------------- node render
  function widgetHtml(id, pref) {
    var name = "f-" + id + "-" + pref.param;
    if (pref.widget === "select") {
      var opts = (pref.options || []).map(function (o) {
        var sel = String(pref.default) === String(o) ? " selected" : "";
        return '<option value="' + esc(o) + '"' + sel + ">" + esc(o) + "</option>";
      }).join("");
      return '<select id="' + name + '" data-field="' + esc(pref.param) + '">' + opts + "</select>";
    }
    if (pref.widget === "checkbox") {
      var ck = pref.default ? " checked" : "";
      return '<input type="checkbox" id="' + name + '" data-field="' + esc(pref.param) + '"' + ck + ">";
    }
    var type = pref.widget === "number" ? "number" : "text";
    return '<input type="' + type + '" id="' + name + '" data-field="' + esc(pref.param) +
      '" value="' + esc(pref.default == null ? "" : pref.default) + '" placeholder="' + esc(pref.placeholder || "") + '">';
  }

  function renderNode(id) {
    var node = editor.getNodeFromId(id);
    var entry = MANIFEST.nodes[node.name];
    var mount = document.querySelector("#node-" + id + " .studio-node");
    if (!mount) return;
    var data = node.data || {};
    var fields = data.fields || {};

    var html = '<div class="node-head"><span>' + esc(entry.label) +
      '</span><span class="node-del" data-role="del" title="Delete">✕</span></div>';
    html += '<div class="node-body">';

    if (node.name === "__csv__") {
      html += "<label>CSV</label><select data-role=\"csv\">";
      CSV_NAMES.forEach(function (n) {
        var sel = data.csv === n ? " selected" : "";
        html += '<option value="' + esc(n) + '"' + sel + ">" + esc(n) + ".csv</option>";
      });
      html += "</select>";
    }

    entry.columns.forEach(function (col) {
      var t = col.accepts[0];
      html += '<div class="field-col"><label>' + esc(col.label) +
        '<span class="wire-badge" data-t="' + esc(t) + '" title="' + esc(col.accepts.join(", ")) + '">' + esc(t) + "</span></label>";
      html += '<input list="dl-' + id + "-" + esc(col.param) + '" data-field="' + esc(col.param) +
        '" value="' + esc(fields[col.param] || "") + '" placeholder="column"><datalist id="dl-' + id + "-" + esc(col.param) + '"></datalist></div>';
    });

    entry.prefs.forEach(function (pref) {
      html += "<label>" + esc(pref.label) + "</label>" + widgetHtml(id, pref);
    });

    if (entry.output) {
      var badge = entry.output.kind === "column"
        ? ' <span class="wire-badge" data-t="' + esc(entry.output.type) + '">' + esc(entry.output.type) + "</span>" : "";
      html += "<label>" + esc(entry.output.label) + badge + "</label>";
      html += '<input type="text" data-field="' + esc(entry.output.param) + '" value="' +
        esc(fields[entry.output.param] == null ? entry.output.default : fields[entry.output.param]) + '">';
    }

    html += "</div>";
    mount.innerHTML = html;
    attachNode(id);
    populateNodeColumns(id);
  }

  function syncNode(id) {
    var node = editor.getNodeFromId(id);
    if (!node) return;
    var el = document.getElementById("node-" + id);
    var data = node.data || { action: node.name, csv: "", fields: {} };
    data.fields = data.fields || {};
    var csvSel = el.querySelector('[data-role="csv"]');
    if (csvSel) data.csv = csvSel.value;
    el.querySelectorAll("[data-field]").forEach(function (c) {
      data.fields[c.getAttribute("data-field")] = c.type === "checkbox" ? c.checked : c.value;
    });
    editor.updateNodeDataFromId(id, data);
  }

  function attachNode(id) {
    var el = document.getElementById("node-" + id);
    if (!el) return;
    var del = el.querySelector('[data-role="del"]');
    if (del) del.addEventListener("click", function () {
      editor.removeNodeId("node-" + id);
      refreshAllColumns();
    });

    var csvSel = el.querySelector('[data-role="csv"]');
    if (csvSel) csvSel.addEventListener("change", function () {
      syncNode(id);
      ensureColumns(csvSel.value).then(refreshAllColumns);
    });

    // Output/new-column names change what downstream nodes can see; refresh all.
    el.querySelectorAll("[data-field]").forEach(function (c) {
      var evt = (c.tagName === "SELECT" || c.type === "checkbox") ? "change" : "input";
      c.addEventListener(evt, function () {
        syncNode(id);
        refreshAllColumns();
      });
    });
  }

  // --------------------------------------------------------- create / drop
  function createNode(action, x, y) {
    var entry = MANIFEST.nodes[action];
    if (!entry) return;
    var inN = (entry.category === "source" || !entry.table_param) ? 0 : 1;
    var outN = entry.table_out === "none" ? 0 : 1;
    var data = { action: action, csv: "", fields: {} };
    entry.prefs.forEach(function (p) { data.fields[p.param] = p.default; });
    if (entry.output) data.fields[entry.output.param] = entry.output.default;
    if (action === "__csv__") data.csv = CSV_NAMES[0] || "";
    var mountHtml = '<div class="studio-node" data-cat="' + esc(entry.category) + '"></div>';
    var id = editor.addNode(action, inN, outN, x, y, "studio-node-wrap", data, mountHtml);
    renderNode(id);
    if (action === "__csv__" && data.csv) ensureColumns(data.csv).then(refreshAllColumns);
    return id;
  }

  function addNodeAt(action, clientX, clientY) {
    var pc = editor.precanvas;
    var rect = pc.getBoundingClientRect();
    var zoom = editor.zoom;
    var x = clientX * (pc.clientWidth / (pc.clientWidth * zoom)) - (rect.x * (pc.clientWidth / (pc.clientWidth * zoom)));
    var y = clientY * (pc.clientHeight / (pc.clientHeight * zoom)) - (rect.y * (pc.clientHeight / (pc.clientHeight * zoom)));
    createNode(action, x, y);
  }

  container.addEventListener("dragover", function (e) { e.preventDefault(); });
  container.addEventListener("drop", function (e) {
    e.preventDefault();
    var action = e.dataTransfer.getData("node");
    if (action) addNodeAt(action, e.clientX, e.clientY);
  });

  // Enforce a single table source per node; refresh projected columns on change.
  editor.on("connectionCreated", function (info) {
    var t = editor.getNodeFromId(info.input_id);
    var cons = (t.inputs.input_1 && t.inputs.input_1.connections) || [];
    if (cons.length > 1) {
      cons.slice(0, cons.length - 1).forEach(function (c) {
        editor.removeSingleConnection(c.node, info.input_id, c.input, "input_1");
      });
    }
    refreshAllColumns();
  });
  editor.on("connectionRemoved", refreshAllColumns);

  // ---------------------------------------------------------------- palette
  (function buildPalette() {
    var pal = document.getElementById("studio-palette");
    MANIFEST.palette.forEach(function (group) {
      var h = document.createElement("h4");
      h.textContent = group.label;
      pal.appendChild(h);
      group.nodes.forEach(function (action) {
        var entry = MANIFEST.nodes[action];
        var item = document.createElement("div");
        item.className = "palette-item";
        item.setAttribute("data-cat", entry.category);
        item.setAttribute("draggable", "true");
        item.textContent = entry.label;
        item.addEventListener("dragstart", function (e) {
          e.dataTransfer.setData("node", action);
        });
        pal.appendChild(item);
      });
    });
  })();

  // ------------------------------------------------------------------- run
  function compile() {
    var data = editor.export().drawflow.Home.data;
    var nodes = [], edges = [];
    Object.keys(data).forEach(function (k) {
      var n = data[k];
      nodes.push({
        id: String(n.id), action: n.name,
        csv: (n.data && n.data.csv) || "",
        fields: (n.data && n.data.fields) || {}
      });
      var outs = (n.outputs.output_1 && n.outputs.output_1.connections) || [];
      outs.forEach(function (c) { edges.push({ from: String(n.id), to: String(c.node) }); });
    });
    return { nodes: nodes, edges: edges };
  }

  var runBtn = document.getElementById("run-btn");
  var runStatus = document.getElementById("run-status");
  var runResults = document.getElementById("run-results");
  var runEmpty = document.getElementById("run-empty");

  function renderRunRows(tasks) {
    var html = "";
    tasks.forEach(function (t) {
      html += '<div class="run-row" data-task="' + esc(t.task_id) + '"><span class="fn">' +
        esc(t.action) + '</span><span class="status-pill queued" data-role="pill">queued</span></div>';
    });
    runStatus.innerHTML = html;
  }

  function pollAll(tasks) {
    var remaining = tasks.slice();
    function tick() {
      if (!remaining.length) { showResults(tasks); return; }
      Promise.all(remaining.map(function (t) {
        return fetch(STATUS_URL.replace("__ID__", encodeURIComponent(t.task_id)))
          .then(function (r) { return r.json(); })
          .then(function (d) { return { t: t, status: d.status || "queued" }; })
          .catch(function () { return { t: t, status: "queued" }; });
      })).then(function (results) {
        results.forEach(function (res) {
          var row = runStatus.querySelector('[data-task="' + res.t.task_id + '"] [data-role="pill"]');
          if (row) { row.textContent = res.status; row.className = "status-pill " + res.status; }
          res.t.status = res.status;
        });
        remaining = remaining.filter(function (t) {
          return ["completed", "failed", "cancelled"].indexOf(t.status) === -1;
        });
        if (remaining.length) setTimeout(tick, 1300); else showResults(tasks);
      });
    }
    tick();
  }

  function showResults(tasks) {
    runBtn.disabled = false;
    runBtn.textContent = "▶ Run pipeline";
    var html = "";
    tasks.forEach(function (t) {
      if (t.category === "visualization" && t.status === "completed" && t.output_name) {
        html += "<h3>" + esc(t.output_name) + ".html</h3><iframe src=\"" +
          esc(HTML_URL.replace("__NAME__", encodeURIComponent(t.output_name))) + '"></iframe>';
      }
    });
    runResults.innerHTML = html;
  }

  runBtn.addEventListener("click", function () {
    var payload = compile();
    if (!payload.nodes.length) { alert("Add some nodes first."); return; }
    if (runEmpty) runEmpty.style.display = "none";
    runBtn.disabled = true;
    runBtn.textContent = "Queuing…";
    runResults.innerHTML = "";
    fetch(RUN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok || res.data.error) {
          runBtn.disabled = false;
          runBtn.textContent = "▶ Run pipeline";
          runStatus.innerHTML = '<p class="message error">' + esc(res.data.error || "Could not run pipeline.") + "</p>";
          return;
        }
        runBtn.textContent = "Running…";
        renderRunRows(res.data.tasks);
        pollAll(res.data.tasks);
      })
      .catch(function () {
        runBtn.disabled = false;
        runBtn.textContent = "▶ Run pipeline";
        runStatus.innerHTML = '<p class="message error">Network error.</p>';
      });
  });

  // Seed the canvas with a CSV input node so the editor isn't blank.
  if (CSV_NAMES.length) createNode("__csv__", 60, 80);
})();
