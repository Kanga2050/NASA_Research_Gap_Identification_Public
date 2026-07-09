/* Studio — visual scripting node editor (Drawflow).
 *
 * Two wire kinds: **csv** (a whole table) and **column** (one typed column of a
 * table: text/number/date/embedding). Each node has one output wire:
 *   CSV Input -> csv ; Select Column (csv in -> dependent dropdown) -> column ;
 *   Annotation (column in) -> column ; Distillation (csv + column in) -> csv ;
 *   Visualization (column in) -> html (terminal).
 * A column wire carries its source CSV, so a function's source CSV is derived from
 * its input wires. Run POSTs {nodes, edges}; the server propagates carriage in
 * topological order and queues each task (per-user FIFO = correct execution order).
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
  var TEMPLATES_URL = root.getAttribute("data-templates-url");
  var TEMPLATE_SAVE_URL = root.getAttribute("data-template-save-url");
  var TEMPLATE_LOAD_URL = root.getAttribute("data-template-load-url");
  var USER_KEY = root.getAttribute("data-user") || "anon";
  var STORAGE_KEY = "studio:graph:" + USER_KEY;

  var columnCache = {}; // csvName -> [{name, type}]

  var container = document.getElementById("drawflow");
  var editor = new Drawflow(container);
  editor.reroute = true;
  editor.start();

  // ---------------------------------------------------- local persistence
  // The canvas is saved to localStorage on every edit and rehydrated on load so
  // it survives tab switches / reloads (tabs are separate full-page routes).
  var restoring = false; // suppress autosave while importing a graph
  var saveTimer = null;
  function saveLocal() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(editor.export())); } catch (e) {}
  }
  function autosave() {
    if (restoring) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveLocal, 400);
  }
  function loadLocal() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function graphHasNodes(graph) {
    try { return Object.keys(graph.drawflow.Home.data).length > 0; }
    catch (e) { return false; }
  }
  // Re-render every node's widgets and rebind its events. Drawflow.import restores
  // node DOM + data but not our event listeners, so rebuild each from node.data.
  function rerenderAllNodes() {
    allNodeIds().forEach(function (id) { renderNode(id); });
  }
  // Replace the canvas with an imported graph (from localStorage or a template).
  function importGraph(graph) {
    restoring = true;
    try {
      editor.clear();
      editor.import(graph);
      rerenderAllNodes();
    } finally { restoring = false; }
    refreshAll();
    saveLocal();
  }

  // ---------------------------------------------------------------- helpers
  function esc(v) {
    return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function mergeCols(a, b) {
    var seen = {}, out = [];
    a.concat(b).forEach(function (c) { if (c && c.name && !seen[c.name]) { seen[c.name] = 1; out.push(c); } });
    return out;
  }
  function ensureColumns(csv) {
    if (!csv || columnCache[csv]) return Promise.resolve();
    return fetch(COLUMNS_URL.replace("__NAME__", encodeURIComponent(csv)))
      .then(function (r) { return r.json(); })
      .then(function (d) { columnCache[csv] = d.typed || []; })
      .catch(function () { columnCache[csv] = []; });
  }
  function allNodeIds() { return Object.keys(editor.export().drawflow.Home.data); }
  function entryOf(id) { var n = editor.getNodeFromId(id); return n ? MANIFEST.nodes[n.name] : null; }

  function producerOf(nodeId, inIdx) {
    var n = editor.getNodeFromId(nodeId);
    var cons = (n.inputs["input_" + (inIdx + 1)] || {}).connections || [];
    return cons.length ? cons[0].node : null;
  }
  function inputIndexOf(entry, param) {
    for (var i = 0; i < entry.inputs.length; i++) if (entry.inputs[i].param === param) return i;
    return -1;
  }

  // -------------------------------------------------- carriage propagation
  // What a node emits on its single output wire: {wire:'csv'|'column'|'none', csv, column, type}
  function resolveOutput(id, seen) {
    seen = seen || {};
    if (seen[id]) return null;
    seen[id] = 1;
    var n = editor.getNodeFromId(id);
    if (!n) return null;
    var e = MANIFEST.nodes[n.name];
    var d = n.data || {};
    var f = d.fields || {};

    if (e.special === "csv_input") return { wire: "csv", csv: d.csv || "" };
    if (e.special === "select_column") {
      var prod = producerOf(id, 0);
      var src = prod ? resolveOutput(prod, seen) : null;
      var csv = src ? src.csv : "";
      var type = "text";
      if (prod) {
        var found = projectedColumns(prod, seen).find(function (c) { return c.name === d.column; });
        if (found) type = found.type;
      }
      return { wire: "column", csv: csv, column: d.column || "", type: type };
    }
    if (e.action === "openalex_scraper") return { wire: "csv", csv: f[e.output.param] || e.output.default };
    if (e.category === "annotation") {
      var c = firstColumnCarry(id, seen);
      return { wire: "column", csv: c ? c.csv : "", column: f[e.output.param] || e.output.default, type: e.output.type };
    }
    if (e.category === "distillation") return { wire: "csv", csv: f[e.output.param] || e.output.default };
    return { wire: "none" };
  }

  function firstColumnCarry(id, seen) {
    var e = entryOf(id);
    for (var i = 0; i < e.inputs.length; i++) {
      if (e.inputs[i].wire === "column") {
        var p = producerOf(id, i);
        if (p) return resolveOutput(p, seen);
      }
    }
    return null;
  }
  function columnCarry(id, param, seen) {
    var e = entryOf(id);
    var idx = inputIndexOf(e, param);
    if (idx < 0) return null;
    var p = producerOf(id, idx);
    return p ? resolveOutput(p, seen) : null;
  }

  // Columns a csv-producing node emits (for Select Column dropdowns).
  function projectedColumns(id, seen) {
    seen = seen || {};
    var key = "pc:" + id;
    if (seen[key]) return [];
    seen[key] = 1;
    var n = editor.getNodeFromId(id);
    if (!n) return [];
    var e = MANIFEST.nodes[n.name];
    var f = (n.data && n.data.fields) || {};
    if (e.special === "csv_input") return (columnCache[n.data.csv] || []).slice();
    if (e.action === "openalex_scraper") return [];
    if (e.category !== "distillation") return [];

    var csvIdx = -1;
    for (var i = 0; i < e.inputs.length; i++) if (e.inputs[i].wire === "csv") { csvIdx = i; break; }
    var up = [];
    if (csvIdx >= 0) { var prod = producerOf(id, csvIdx); if (prod) up = projectedColumns(prod, seen); }

    if (e.projects === "passthrough") return up;
    if (e.projects === "arithmetic") return mergeCols(up, [{ name: f.new_column_name || "result", type: "number" }]);
    if (e.projects === "group_aggregate") {
      var g = columnCarry(id, "group_column", seen);
      var v = columnCarry(id, "value_column", seen);
      var agg = f.agg || "count";
      var valName = (agg === "count" || !v) ? "count" : (v.column + "_" + agg);
      var out = [];
      if (g) out.push({ name: g.column, type: g.type || "text" });
      out.push({ name: valName, type: "number" });
      return out;
    }
    return []; // replace / unknown -> Select Column will show none
  }

  // ------------------------------------------------------------ node render
  function widgetHtml(id, pref) {
    var name = "f-" + id + "-" + pref.param;
    if (pref.widget === "select") {
      var opts = (pref.options || []).map(function (o) {
        return '<option value="' + esc(o) + '"' + (String(pref.default) === String(o) ? " selected" : "") + ">" + esc(o) + "</option>";
      }).join("");
      return '<select id="' + name + '" data-field="' + esc(pref.param) + '">' + opts + "</select>";
    }
    if (pref.widget === "checkbox") {
      return '<input type="checkbox" id="' + name + '" data-field="' + esc(pref.param) + '"' + (pref.default ? " checked" : "") + ">";
    }
    var type = pref.widget === "number" ? "number" : "text";
    return '<input type="' + type + '" id="' + name + '" data-field="' + esc(pref.param) +
      '" value="' + esc(pref.default == null ? "" : pref.default) + '" placeholder="' + esc(pref.placeholder || "") + '">';
  }

  function renderNode(id) {
    var n = editor.getNodeFromId(id);
    var e = MANIFEST.nodes[n.name];
    var mount = document.querySelector("#node-" + id + " .studio-node");
    if (!mount) return;
    var f = (n.data && n.data.fields) || {};

    var html = '<div class="node-head"><span>' + esc(e.label) +
      '</span><span class="node-del" data-role="del" title="Delete">✕</span></div><div class="node-body">';

    if (e.special === "csv_input") {
      html += '<label>CSV</label><select data-role="csv">';
      CSV_NAMES.forEach(function (c) {
        html += '<option value="' + esc(c) + '"' + ((n.data && n.data.csv) === c ? " selected" : "") + ">" + esc(c) + ".csv</option>";
      });
      html += "</select>";
    } else if (e.special === "select_column") {
      html += '<label>Column <span class="wire-badge" data-role="outbadge" data-t="text">text</span></label>';
      html += '<select data-role="colpick"><option value="">Connect a CSV…</option></select>';
    }

    // Input ports (function nodes)
    e.inputs.forEach(function (inp) {
      var badge = inp.wire === "csv"
        ? '<span class="wire-badge" data-t="csv">csv</span>'
        : '<span class="wire-badge" data-t="' + esc(inp.accepts[0]) + '" title="' + esc(inp.accepts.join(", ")) + '">' + esc(inp.accepts[0]) + "</span>";
      html += '<div class="port-in">' + badge + " " + esc(inp.label) + (inp.optional ? " <em>(opt)</em>" : "") + "</div>";
    });

    e.prefs.forEach(function (pref) { html += "<label>" + esc(pref.label) + "</label>" + widgetHtml(id, pref); });

    // Output-name field (annotation new column / distillation csv / viz html)
    if (e.output && e.output.param && e.special !== "csv_input" && e.special !== "select_column") {
      var lbl = e.output.kind === "column" ? "New column" : (e.output.kind === "csv" ? "Output CSV" : "Output HTML");
      html += "<label>" + lbl + "</label><input type=\"text\" data-field=\"" + esc(e.output.param) +
        '" value="' + esc(f[e.output.param] == null ? e.output.default : f[e.output.param]) + '">';
    }

    // Output port label (non-terminal)
    if (e.category !== "visualization" && e.special !== "csv_input" && e.special !== "select_column") {
      var ot = e.output.kind === "column" ? e.output.type : "csv";
      html += '<div class="port-out"><span data-role="outlabel"></span> <span class="wire-badge" data-role="outbadge" data-t="' + esc(ot) + '">' + esc(ot) + "</span></div>";
    } else if (e.special === "csv_input") {
      html += '<div class="port-out"><span data-role="outlabel"></span> <span class="wire-badge" data-t="csv">csv</span></div>';
    }

    html += "</div>";
    mount.innerHTML = html;
    attachNode(id);
  }

  function syncNode(id) {
    var n = editor.getNodeFromId(id);
    if (!n) return;
    var el = document.getElementById("node-" + id);
    var data = n.data || { action: n.name, csv: "", column: "", fields: {} };
    data.fields = data.fields || {};
    var csvSel = el.querySelector('[data-role="csv"]');
    if (csvSel) data.csv = csvSel.value;
    var colSel = el.querySelector('[data-role="colpick"]');
    if (colSel) data.column = colSel.value;
    el.querySelectorAll("[data-field]").forEach(function (c) {
      data.fields[c.getAttribute("data-field")] = c.type === "checkbox" ? c.checked : c.value;
    });
    editor.updateNodeDataFromId(id, data);
  }

  function attachNode(id) {
    var el = document.getElementById("node-" + id);
    if (!el) return;
    var del = el.querySelector('[data-role="del"]');
    if (del) del.addEventListener("click", function () { editor.removeNodeId("node-" + id); refreshAll(); });

    var csvSel = el.querySelector('[data-role="csv"]');
    if (csvSel) csvSel.addEventListener("change", function () { syncNode(id); ensureColumns(csvSel.value).then(refreshAll); });

    var colSel = el.querySelector('[data-role="colpick"]');
    if (colSel) colSel.addEventListener("change", function () { syncNode(id); refreshAll(); });

    el.querySelectorAll("[data-field]").forEach(function (c) {
      var evt = (c.tagName === "SELECT" || c.type === "checkbox") ? "change" : "input";
      c.addEventListener(evt, function () { syncNode(id); refreshAll(); });
    });
  }

  // --------------------------------------------------------------- refresh
  function updateOutLabel(id) {
    var el = document.getElementById("node-" + id);
    if (!el) return;
    var out = resolveOutput(id, {});
    var lbl = el.querySelector('[data-role="outlabel"]');
    var badge = el.querySelector('[data-role="outbadge"]');
    if (out && lbl) lbl.textContent = out.wire === "csv" ? ((out.csv || "?") + ".csv") : (out.column || "?");
    if (out && out.wire === "column" && badge) { badge.textContent = out.type || "text"; badge.setAttribute("data-t", out.type || "text"); }
  }

  function populateSelectColumn(id) {
    var n = editor.getNodeFromId(id);
    if (!n || MANIFEST.nodes[n.name].special !== "select_column") return;
    var sel = document.querySelector("#node-" + id + ' [data-role="colpick"]');
    if (!sel) return;
    var prod = producerOf(id, 0);
    var prev = (n.data && n.data.column) || sel.value;
    sel.innerHTML = "";
    if (!prod) { sel.innerHTML = '<option value="">Connect a CSV…</option>'; return; }
    var cols = projectedColumns(prod, {});
    if (!cols.length) { sel.innerHTML = '<option value="">No columns…</option>'; return; }
    cols.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c.name; o.textContent = c.name + "  (" + c.type + ")";
      sel.appendChild(o);
    });
    if (cols.some(function (c) { return c.name === prev; })) sel.value = prev;
    syncNode(id);
  }

  function refreshAll() {
    var ids = allNodeIds();
    var csvs = ids.map(function (id) { return editor.getNodeFromId(id); })
      .filter(function (n) { return n && MANIFEST.nodes[n.name].special === "csv_input"; })
      .map(function (n) { return n.data.csv; }).filter(Boolean);
    Promise.all(csvs.map(ensureColumns)).then(function () {
      ids.forEach(function (id) { populateSelectColumn(id); updateOutLabel(id); });
    });
  }

  // --------------------------------------------------------- create / drop
  function createNode(action, x, y) {
    var e = MANIFEST.nodes[action];
    if (!e) return;
    var inN = e.inputs.length;
    var outN = (e.category === "visualization") ? 0 : 1;
    var data = { action: action, csv: "", column: "", fields: {} };
    e.prefs.forEach(function (p) { data.fields[p.param] = p.default; });
    if (e.output && e.output.param) data.fields[e.output.param] = e.output.default;
    if (e.special === "csv_input") data.csv = CSV_NAMES[0] || "";
    var id = editor.addNode(action, inN, outN, x, y, "studio-node-wrap", data,
      '<div class="studio-node" data-cat="' + esc(e.category) + '"></div>');
    renderNode(id);
    if (e.special === "csv_input" && data.csv) ensureColumns(data.csv).then(refreshAll); else refreshAll();
    return id;
  }

  function addNodeAt(action, clientX, clientY) {
    var pc = editor.precanvas, rect = pc.getBoundingClientRect(), zoom = editor.zoom;
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

  // ----------------------------------------------------- connection typing
  function flash(msg) {
    var hint = document.querySelector(".studio-hint");
    if (!hint) return;
    var old = hint.textContent;
    hint.textContent = "⚠ " + msg;
    hint.style.color = "#e4002b";
    setTimeout(function () { hint.textContent = old; hint.style.color = ""; }, 2600);
  }
  function reject(info, msg) {
    editor.removeSingleConnection(info.output_id, info.input_id, info.output_class, info.input_class);
    flash(msg);
  }

  editor.on("connectionCreated", function (info) {
    var tgt = editor.getNodeFromId(info.input_id);
    var te = MANIFEST.nodes[tgt.name];
    var inIdx = parseInt(info.input_class.split("_")[1], 10) - 1;
    var inp = te.inputs[inIdx];

    // one wire per input port
    var cons = (tgt.inputs[info.input_class] || {}).connections || [];
    if (cons.length > 1) {
      cons.slice(0, cons.length - 1).forEach(function (c) {
        editor.removeSingleConnection(c.node, info.input_id, c.input, info.input_class);
      });
    }
    if (!inp) { reject(info, "Unknown input."); return; }

    var srcOut = resolveOutput(info.output_id, {});
    var srcWire = srcOut ? srcOut.wire : null;
    if (srcWire && srcWire !== inp.wire) { reject(info, "Expected a " + inp.wire + " wire, got " + srcWire + "."); return; }
    if (inp.wire === "column" && inp.accepts && inp.accepts.length && srcOut && srcOut.type &&
        inp.accepts.indexOf(srcOut.type) === -1) {
      reject(info, srcOut.type + " column not accepted here (" + inp.accepts.join("/") + ")."); return;
    }
    refreshAll();
  });
  editor.on("connectionRemoved", refreshAll);

  // Any node removal (✕ button, Delete/Backspace key, or context menu) must
  // re-derive columns/labels; every graph edit is persisted to localStorage.
  editor.on("nodeRemoved", function () { refreshAll(); autosave(); });
  editor.on("nodeCreated", autosave);
  editor.on("nodeDataChanged", autosave);
  editor.on("nodeMoved", autosave);
  editor.on("connectionCreated", autosave);
  editor.on("connectionRemoved", autosave);

  // --------------------------------------------------------------- palette
  (function buildPalette() {
    var pal = document.getElementById("studio-palette");
    MANIFEST.palette.forEach(function (group) {
      var h = document.createElement("h4"); h.textContent = group.label; pal.appendChild(h);
      group.nodes.forEach(function (action) {
        var e = MANIFEST.nodes[action];
        var item = document.createElement("div");
        item.className = "palette-item";
        item.setAttribute("data-cat", e.category);
        item.setAttribute("draggable", "true");
        item.textContent = e.label;
        item.addEventListener("dragstart", function (ev) { ev.dataTransfer.setData("node", action); });
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
      nodes.push({ id: String(n.id), action: n.name, csv: (n.data && n.data.csv) || "",
        column: (n.data && n.data.column) || "", fields: (n.data && n.data.fields) || {} });
      Object.keys(n.outputs || {}).forEach(function (outCls) {
        (n.outputs[outCls].connections || []).forEach(function (c) {
          edges.push({ from: String(n.id), to: String(c.node), toPort: parseInt(c.output.split("_")[1], 10) - 1 });
        });
      });
    });
    return { nodes: nodes, edges: edges };
  }

  var runBtn = document.getElementById("run-btn");
  var runStatus = document.getElementById("run-status");
  var runResults = document.getElementById("run-results");
  var runEmpty = document.getElementById("run-empty");

  function renderRunRows(tasks) {
    runStatus.innerHTML = tasks.map(function (t) {
      return '<div class="run-row" data-task="' + esc(t.task_id) + '"><span class="fn">' + esc(t.action) +
        '</span><span class="status-pill queued" data-role="pill">queued</span></div>';
    }).join("");
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
          var pill = runStatus.querySelector('[data-task="' + res.t.task_id + '"] [data-role="pill"]');
          if (pill) { pill.textContent = res.status; pill.className = "status-pill " + res.status; }
          res.t.status = res.status;
        });
        remaining = remaining.filter(function (t) { return ["completed", "failed", "cancelled"].indexOf(t.status) === -1; });
        if (remaining.length) setTimeout(tick, 1300); else showResults(tasks);
      });
    }
    tick();
  }

  function showResults(tasks) {
    runBtn.disabled = false;
    runBtn.textContent = "▶ Run pipeline";
    runResults.innerHTML = tasks.filter(function (t) {
      return t.category === "visualization" && t.status === "completed" && t.output_name;
    }).map(function (t) {
      return "<h3>" + esc(t.output_name) + ".html</h3><iframe src=\"" +
        esc(HTML_URL.replace("__NAME__", encodeURIComponent(t.output_name))) + '"></iframe>';
    }).join("");
  }

  runBtn.addEventListener("click", function () {
    var payload = compile();
    if (!payload.nodes.length) { flash("Add some nodes first."); return; }
    if (runEmpty) runEmpty.style.display = "none";
    runBtn.disabled = true;
    runBtn.textContent = "Queuing…";
    runResults.innerHTML = "";
    fetch(RUN_URL, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok || res.data.error) {
          runBtn.disabled = false; runBtn.textContent = "▶ Run pipeline";
          runStatus.innerHTML = '<p class="message error">' + esc(res.data.error || "Could not run pipeline.") + "</p>";
          return;
        }
        runBtn.textContent = "Running…";
        renderRunRows(res.data.tasks);
        pollAll(res.data.tasks);
      })
      .catch(function () {
        runBtn.disabled = false; runBtn.textContent = "▶ Run pipeline";
        runStatus.innerHTML = '<p class="message error">Network error.</p>';
      });
  });

  // ------------------------------------------------------- templates + clear
  var templateSelect = document.getElementById("template-load");
  var saveTemplateBtn = document.getElementById("save-template-btn");
  var clearBtn = document.getElementById("clear-canvas-btn");

  function refreshTemplateList() {
    if (!templateSelect || !TEMPLATES_URL) return;
    fetch(TEMPLATES_URL, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var items = d.templates || [];
        templateSelect.innerHTML = '<option value="">Load a template…</option>' +
          items.map(function (t) {
            var label = t.description ? t.name + " — " + t.description : t.name;
            return '<option value="' + esc(t.name) + '">' + esc(label) + "</option>";
          }).join("");
      })
      .catch(function () {});
  }

  if (saveTemplateBtn) saveTemplateBtn.addEventListener("click", function () {
    var payload = compile();
    if (!payload.nodes.length) { flash("Add some nodes before saving a template."); return; }
    var name = (prompt("Template name:") || "").trim();
    if (!name) return;
    var description = (prompt("Description (optional):") || "").trim();
    fetch(TEMPLATE_SAVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      body: JSON.stringify({ name: name, description: description, graph: editor.export() })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok || res.data.error) { flash(res.data.error || "Could not save template."); return; }
        flash("Saved template “" + res.data.name + "”.");
        refreshTemplateList();
      })
      .catch(function () { flash("Network error saving template."); });
  });

  if (templateSelect) templateSelect.addEventListener("change", function () {
    var name = templateSelect.value;
    if (!name) return;
    fetch(TEMPLATE_LOAD_URL.replace("__NAME__", encodeURIComponent(name)), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error || !d.graph) { flash(d.error || "Could not load template."); return; }
        importGraph(d.graph);
      })
      .catch(function () { flash("Network error loading template."); })
      .then(function () { templateSelect.value = ""; });
  });

  if (clearBtn) clearBtn.addEventListener("click", function () {
    if (!confirm("Clear the canvas? This removes all nodes.")) return;
    restoring = true;
    try { editor.clear(); } finally { restoring = false; }
    if (CSV_NAMES.length) createNode("__csv__", 40, 60);
    saveLocal();
  });

  // Restore the saved canvas if present; otherwise seed a starter CSV node so
  // the editor isn't blank.
  var saved = loadLocal();
  if (saved && graphHasNodes(saved)) {
    importGraph(saved);
  } else if (CSV_NAMES.length) {
    createNode("__csv__", 40, 60);
  }

  refreshTemplateList();
})();
