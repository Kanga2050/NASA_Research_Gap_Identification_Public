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

  // Frozen block definitions this canvas carries: name -> {header, body}. A pipeline
  // travels with the blocks it uses, so it stays runnable and portable on its own.
  var BLOCKS = {};
  var BLOCK_PREFIX = "@";

  function isInstance(action) { return !!action && action.indexOf(BLOCK_PREFIX) === 0; }
  function blockNameOf(action) { return action.slice(BLOCK_PREFIX.length); }

  // The manifest entry for a node -- synthesised from the block's own interface when
  // the node is a composite, so every other function here treats it like any node.
  function entryFor(action) {
    if (!isInstance(action)) return MANIFEST.nodes[action];
    var block = BLOCKS[blockNameOf(action)];
    if (!block) return null;
    var h = block.header;
    return {
      action: action, label: h.name || blockNameOf(action), category: "block",
      inputs: h.inputs.map(function (p) {
        return { param: "__in_" + p.port + "__", label: p.name, wire: p.wire || "any",
                 accepts: p.accepts || [], optional: false };
      }),
      prefs: (function () {
        // one field per promoted NAME: a name may drive several inner parameters
        var seen = {}, out = [];
        h.params.forEach(function (p) {
          if (seen[p.name]) return;
          seen[p.name] = 1;
          out.push({ param: p.name, label: p.name, widget: "text", default: p.default, options: [] });
        });
        return out;
      })(),
      output: { param: null, kind: "block", default: "" },
      outputs: h.outputs, special: "block_instance", projects: null, variadic: null
    };
  }

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
    try {
      var snapshot = editor.export();
      snapshot.blocks = BLOCKS;                 // the canvas travels with its blocks
      localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    } catch (e) {}
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
  function importGraph(graph, tidy) {
    restoring = true;
    BLOCKS = (graph && graph.blocks) || {};
    try {
      editor.clear();
      editor.import(graph);
      rerenderAllNodes();
    } finally { restoring = false; }
    // A freshly loaded template is re-laid-out client-side (pipeline band on top, each
    // block definition in its own band below) so boundary nodes sit with their block
    // rather than trailing off the bottom. Skipped when restoring the local draft, which
    // already holds the positions the user last saw.
    if (tidy !== false && container.offsetParent) layoutGraph();
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
  // Drawflow throws when asked for a node that no longer exists, and a connection can
  // outlive its node for a tick -- grouping removes a whole selection at once. Every
  // lookup goes through here so a stale id is a null, not an exception.
  function nodeById(id) {
    try {
      var data = editor.drawflow.drawflow[editor.module].data;
      return Object.prototype.hasOwnProperty.call(data, id) ? editor.getNodeFromId(id) : null;
    } catch (e) { return null; }
  }

  function entryOf(id) { var n = nodeById(id); return n ? entryFor(n.name) : null; }

  function producerOf(nodeId, inIdx) {
    var n = nodeById(nodeId);
    if (!n) return null;
    var cons = (n.inputs["input_" + (inIdx + 1)] || {}).connections || [];
    var live = cons.filter(function (c) { return nodeById(c.node); });
    return live.length ? live[0].node : null;
  }

  // Which output port of the producer feeds this input (blocks emit several).
  function producerPort(nodeId, inIdx) {
    var n = nodeById(nodeId);
    if (!n) return 0;
    var cons = (n.inputs["input_" + (inIdx + 1)] || {}).connections || [];
    if (!cons.length) return 0;
    var m = /output_(\d+)/.exec(cons[0].input || "output_1");
    return m ? parseInt(m[1], 10) - 1 : 0;
  }

  // How many output ports a node instance has.
  function outPortCount(entry, id) {
    if (!entry) return 0;
    if (entry.special === "block_instance") return Math.max(1, (entry.outputs || []).length);
    if (entry.special === "block_in") {
      var n = nodeById(id);
      return n ? Math.max(1, Object.keys(n.outputs || {}).length) : 1;
    }
    if (entry.output.kind === null || entry.output.kind === "html") return 0;
    return 1;
  }
  // The input ports of one node INSTANCE. A variadic node (Combine CSVs) can be given
  // more ports on the canvas, so its real count lives on the node; ports past the
  // declared ones repeat the variadic spec.
  function portSpecs(entry, id) {
    var specs = (entry.inputs || []).slice();
    if (!entry.variadic) return specs;
    // A Block Inputs boundary grows on its OUTPUT side; it has no input ports at all.
    if (entry.variadic.side === "output") return [];
    var n = nodeById(id);
    var count = n ? Object.keys(n.inputs || {}).length : specs.length;
    count = Math.max(entry.variadic.min, Math.min(count, entry.variadic.max));
    while (specs.length < count) {
      specs.push({ param: "__" + entry.variadic.wire + "_" + (specs.length + 1) + "__",
                   label: entry.variadic.label + " " + (specs.length + 1),
                   wire: entry.variadic.wire, optional: true,
                   accepts: entry.variadic.accepts || ["text", "number", "date", "embedding"] });
    }
    return specs.slice(0, count);
  }

  function inputIndexOf(entry, param) {
    for (var i = 0; i < entry.inputs.length; i++) if (entry.inputs[i].param === param) return i;
    return -1;
  }

  // -------------------------------------------------- carriage propagation
  // What a node emits on its single output wire: {wire:'csv'|'column'|'none', csv, column, type}
  function resolveOutput(id, seen, port) {
    seen = seen || {};
    if (seen[id]) return null;
    seen[id] = 1;
    var n = nodeById(id);
    if (!n) return null;
    var e = entryFor(n.name);
    if (!e) return null;
    var d = n.data || {};
    var f = d.fields || {};

    if (e.special === "csv_input") return { wire: "csv", csv: d.csv || "" };
    if (e.special === "block_in") {
      // Inside a definition, a block input stands for whatever the caller will wire in.
      // Its wire kind and type are read from the inner port it feeds, so the definition
      // type-checks and its ports label themselves.
      var bi = boundaryInfo(id)[port || 0] || {};
      var labels = d.fields && d.fields.labels ? d.fields.labels : [];
      return { wire: (bi.wire && bi.wire !== "any") ? bi.wire : "column", csv: "",
               column: labels[port || 0] || bi.name || "schema input",
               type: (bi.type && bi.type !== "any") ? bi.type : "text", boundary: true };
    }
    if (e.special === "block_instance") {
      var outs = e.outputs || [];
      var spec = outs[port || 0] || outs[0] || {};
      return spec.kind === "csv"
        ? { wire: "csv", csv: spec.name || "" }
        : { wire: "column", csv: spec.csv || "", column: spec.name || "", type: spec.type || "text" };
    }
    if (e.special === "select_column") {
      var prod = producerOf(id, 0);
      var src = prod ? resolveOutput(prod, seen, producerPort(id, 0)) : null;
      var csv = src ? src.csv : "";
      var type = "text";
      if (prod) {
        var found = projectedColumns(prod, seen, producerPort(id, 0)).find(function (c) { return c.name === d.column; });
        if (found) type = found.type;
      }
      return { wire: "column", csv: csv, column: d.column || "", type: type };
    }
    // An importer (OpenAlex, PDF chunker, Task Book parser) emits the table it writes.
    if (e.category === "source") return { wire: "csv", csv: f[e.output.param] || e.output.default };
    if (e.category === "annotation") {
      var c = firstColumnCarry(id, seen);
      return { wire: "column", csv: c ? c.csv : "", column: f[e.output.param] || e.output.default, type: e.output.type };
    }
    if (e.category === "distillation") return { wire: "csv", csv: f[e.output.param] || e.output.default };
    return { wire: "none" };
  }

  function firstColumnCarry(id, seen) {
    var e = entryOf(id);
    var specs = portSpecs(e, id);
    for (var i = 0; i < specs.length; i++) {
      if (specs[i].wire === "column") {
        var p = producerOf(id, i);
        if (p) return resolveOutput(p, seen, producerPort(id, i));
      }
    }
    return null;
  }
  function columnCarry(id, param, seen) {
    var e = entryOf(id);
    var idx = inputIndexOf(e, param);
    if (idx < 0) return null;
    var p = producerOf(id, idx);
    return p ? resolveOutput(p, seen, producerPort(id, idx)) : null;
  }

  // Columns a csv-producing node emits (for Select Column dropdowns). `seen` memoizes
  // the RESULT per node, not merely that we have been there: a stack whose two branches
  // share an upstream node would otherwise see the second visit return nothing.
  function projectedColumns(id, seen, port) {
    seen = seen || {};
    port = port || 0;
    var key = "pc:" + id + ":" + port;
    if (Object.prototype.hasOwnProperty.call(seen, key)) return (seen[key] || []).slice();
    seen[key] = [];                                   // cycle guard until we know better
    var out = computeProjectedColumns(id, seen, port) || [];
    seen[key] = out;
    return out.slice();
  }

  function computeProjectedColumns(id, seen, port) {
    var n = nodeById(id);
    if (!n) return [];
    var e = entryFor(n.name);
    if (!e) return [];
    var f = (n.data && n.data.fields) || {};
    if (e.special === "csv_input") return (columnCache[n.data.csv] || []).slice();
    // A schema instance's columns are traced through the schema's own definition (which
    // this canvas always carries), so a Select Column after a schema offers real columns.
    if (e.special === "block_instance") return blockBodyColumns(blockNameOf(n.name), port || 0, id, seen, 0);
    // An importer's columns are fixed by the importer, not by the graph: offer its known
    // schema straight away, merged with the real header once the table it writes exists.
    if (e.category === "source") return mergeCols(e.columns || [], columnCache[f[e.output.param] || e.output.default] || []);
    if (e.category !== "distillation") return [];

    var specs = portSpecs(e, id);
    var csvIdx = -1;
    for (var i = 0; i < specs.length; i++) if (specs[i].wire === "csv") { csvIdx = i; break; }
    var up = [];
    if (csvIdx >= 0) { var prod = producerOf(id, csvIdx); if (prod) up = projectedColumns(prod, seen, producerPort(id, csvIdx)); }

    if (e.projects === "passthrough") return up;
    if (e.projects === "combine") {
      // A stack is the outer union of its inputs' columns, plus the tag naming which
      // table each row came from.
      var all = up;
      for (var j = csvIdx + 1; j < specs.length; j++) {
        if (specs[j].wire !== "csv") continue;
        var other = producerOf(id, j);
        if (other) all = mergeCols(all, projectedColumns(other, seen, producerPort(id, j)));
      }
      return mergeCols(all, [{ name: f.source_column || "source", type: "text" }]);
    }
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
    // "replace" reshapes the table wholesale (a cross-tab, a counts table), so its columns
    // cannot be derived from upstream either -- fall back to the written table, same as an
    // importer above.
    return (columnCache[f[e.output.param] || e.output.default] || []).slice();
  }

  // Columns a schema instance emits on output `outPort`, traced through the schema's
  // frozen body (which the canvas always carries). `instId` lets a schema-input port
  // resolve to whatever the caller wired in, so pass-through columns are the real ones;
  // a nested schema resolves its own internals (but not the outer caller's inputs -- a
  // saved column still shows through the Select Column fallback). All projection rules
  // mirror computeProjectedColumns, over the body graph instead of the live canvas.
  function blockBodyColumns(name, outPort, instId, seen, depth) {
    var block = BLOCKS[name];
    if (!block || !block.body || !block.header || (depth || 0) > 8) return [];
    var header = block.header, body = block.body;
    var outs = header.outputs || [];
    var outSpec = null;
    for (var oi = 0; oi < outs.length; oi++) if (outs[oi].port === (outPort || 0)) { outSpec = outs[oi]; break; }
    if (!outSpec) outSpec = outs[0];
    if (!outSpec) return [];
    var nById = {};
    body.nodes.forEach(function (bn) { nById[String(bn.id)] = bn; });

    function producerIn(bodyId, toPort) {          // internal producer feeding a port
      var res = null;
      body.edges.forEach(function (ed) {
        if (String(ed.to) === String(bodyId) && (ed.toPort || 0) === toPort)
          res = { node: String(ed.from), port: ed.fromPort || 0 };
      });
      return res;
    }
    function callerPort(bodyId, toPort) {          // which schema input feeds a port
      var found = null;
      (header.inputs || []).forEach(function (inp) {
        (inp.targets || [{ node: inp.node, to_port: inp.to_port }]).forEach(function (t) {
          if (String(t.node) === String(bodyId) && (t.to_port || 0) === toPort) found = inp.port;
        });
      });
      return found;
    }
    var memo = {};
    function cols(bodyId) {
      if (memo[bodyId]) return memo[bodyId].slice();
      memo[bodyId] = [];
      var bn = nById[String(bodyId)]; if (!bn) return [];
      var e = entryFor(bn.action); if (!e) return [];
      var f = bn.fields || {};
      var res;
      if (isInstance(bn.action)) res = blockBodyColumns(blockNameOf(bn.action), 0, null, seen, (depth || 0) + 1);
      else if (e.special === "csv_input") res = (columnCache[bn.csv] || []).slice();
      else if (e.category === "source") res = mergeCols(e.columns || [], columnCache[f[e.output.param] || e.output.default] || []);
      else if (e.category !== "distillation") res = [];
      else res = distill(bn, e, f, bodyId);
      memo[bodyId] = res; return res.slice();
    }
    function upCols(bodyId, toPort) {              // columns feeding an input port
      var p = producerIn(bodyId, toPort);
      if (p) return cols(p.node);
      var cp = callerPort(bodyId, toPort);
      if (cp != null && instId != null) { var u = producerOf(instId, cp); if (u) return projectedColumns(u, seen, producerPort(instId, cp)); }
      return [];
    }
    function upCarry(bodyId, toPort) {             // the single column feeding a port
      var p = producerIn(bodyId, toPort);
      if (p) return outCarry(p.node, p.port);
      var cp = callerPort(bodyId, toPort);
      if (cp != null && instId != null) { var u = producerOf(instId, cp); if (u) return resolveOutput(u, seen, producerPort(instId, cp)); }
      return null;
    }
    function outCarry(bodyId, prt) {               // what a body node emits on a wire
      var bn = nById[String(bodyId)]; if (!bn) return null;
      var e = entryFor(bn.action); if (!e) return null;
      var f = bn.fields || {};
      if (isInstance(bn.action)) {
        var bc = blockBodyColumns(blockNameOf(bn.action), prt || 0, null, seen, (depth || 0) + 1);
        return bc[0] ? { wire: "column", column: bc[0].name, type: bc[0].type } : { wire: "csv" };
      }
      if (e.special === "select_column") return { wire: "column", column: bn.column || "", type: "text" };
      if (e.category === "annotation") return { wire: "column", column: f[e.output.param] || e.output.default, type: e.output.type };
      return { wire: "csv" };
    }
    function distill(bn, e, f, bodyId) {
      var specs = e.inputs || [];
      var csvIdx = -1;
      for (var i = 0; i < specs.length; i++) if (specs[i].wire === "csv") { csvIdx = i; break; }
      if (csvIdx < 0 && e.variadic && e.variadic.wire === "csv") csvIdx = 0;
      var up = csvIdx >= 0 ? upCols(bodyId, csvIdx) : [];
      if (e.projects === "passthrough") return up;
      if (e.projects === "combine") {
        var all = up, count = bn.ports || specs.length;
        for (var j = csvIdx + 1; j < count; j++) all = mergeCols(all, upCols(bodyId, j));
        return mergeCols(all, [{ name: f.source_column || "source", type: "text" }]);
      }
      if (e.projects === "arithmetic") return mergeCols(up, [{ name: f.new_column_name || "result", type: "number" }]);
      if (e.projects === "group_aggregate") {
        var gi = inputIndexOf(e, "group_column"), vi = inputIndexOf(e, "value_column");
        var g = gi >= 0 ? upCarry(bodyId, gi) : null, v = vi >= 0 ? upCarry(bodyId, vi) : null;
        var agg = f.agg || "count";
        var valName = (agg === "count" || !v) ? "count" : ((v.column || "value") + "_" + agg);
        var res = [];
        if (g && g.column) res.push({ name: g.column, type: g.type || "text" });
        res.push({ name: valName, type: "number" });
        return res;
      }
      return (columnCache[f[e.output.param] || e.output.default] || []).slice();
    }
    return cols(outSpec.node);
  }

  // The type + title each boundary port should show, read from the wire on it: a Schema
  // Inputs OUTPUT port takes the kind/type/label of the inner port it feeds; a Schema
  // Outputs INPUT port takes them from the producer wired into it. This is what makes a
  // definition's ports label and type-badge themselves as it is wired up.
  function boundaryInfo(id) {
    var n = nodeById(id); if (!n) return [];
    var e = entryFor(n.name); if (!e) return [];
    var labels = ((n.data && n.data.fields) || {}).labels || [];
    var out = [];
    if (e.special === "block_in") {
      var oc = Object.keys(n.outputs || {}).length;
      for (var p = 0; p < oc; p++) {
        var info = { name: labels[p] || ("In " + (p + 1)), type: "any", wire: "any" };
        var cons = ((n.outputs["output_" + (p + 1)] || {}).connections) || [];
        var live = cons.filter(function (c) { return nodeById(c.node); });
        if (live.length) {
          var t = live[0], te = entryOf(t.node);
          var tin = parseInt((t.output || "input_1").split("_")[1], 10) - 1;
          var spec = te ? portSpecs(te, t.node)[tin] : null;
          if (spec) {
            info.wire = spec.wire;
            info.type = spec.wire === "csv" ? "csv" : ((spec.accepts && spec.accepts[0]) || "any");
            if (!labels[p]) info.name = spec.label || info.name;
          }
        }
        out.push(info);
      }
      return out;
    }
    if (e.special === "block_out") {
      var ic = Object.keys(n.inputs || {}).length;
      for (var q = 0; q < ic; q++) {
        var i2 = { name: labels[q] || ("Out " + (q + 1)), type: "any", wire: "any" };
        var prod = producerOf(id, q);
        if (prod) {
          var so = resolveOutput(prod, {}, producerPort(id, q));
          if (so) {
            i2.wire = so.wire;
            i2.type = so.wire === "csv" ? "csv" : (so.type || "any");
            if (!labels[q]) i2.name = so.column || so.csv || i2.name;
          }
        }
        out.push(i2);
      }
      return out;
    }
    return [];
  }

  // Re-label and re-type a boundary node's ports in place from the current wiring, so
  // the ports track what they connect to without a full re-render clobbering the node.
  function updateBoundaryPorts(id) {
    var el = document.getElementById("node-" + id); if (!el) return;
    var n = nodeById(id); if (!n) return;
    var e = entryFor(n.name); if (!e || (e.special !== "block_in" && e.special !== "block_out")) return;
    var info = boundaryInfo(id);
    var rows = el.querySelectorAll(e.special === "block_in" ? '[data-role="bport-out"]' : '[data-role="bport-in"]');
    rows.forEach(function (row, i) {
      var d = info[i]; if (!d) return;
      var nameEl = row.querySelector('[data-role="bname"]');
      var badge = row.querySelector(".wire-badge");
      if (nameEl) nameEl.textContent = d.name;
      if (badge) { badge.textContent = d.type; badge.setAttribute("data-t", d.type); }
    });
  }

  // ------------------------------------------------------------ node render
  // `f` is the node's saved fields: a widget shows the node's own value and falls
  // back to the manifest default only when the node has none. (Rendering the default
  // unconditionally would silently show the wrong parameters for every imported
  // graph -- a template, a restored canvas, or a pipeline the assistant wrote.)
  function widgetHtml(id, pref, f) {
    var name = "f-" + id + "-" + pref.param;
    var val = (f && f[pref.param] != null) ? f[pref.param] : pref.default;
    if (pref.widget === "select") {
      var opts = (pref.options || []).map(function (o) {
        return '<option value="' + esc(o) + '"' + (String(val) === String(o) ? " selected" : "") + ">" + esc(o) + "</option>";
      }).join("");
      return '<select id="' + name + '" data-field="' + esc(pref.param) + '">' + opts + "</select>";
    }
    if (pref.widget === "checkbox") {
      return '<input type="checkbox" id="' + name + '" data-field="' + esc(pref.param) + '"' + (val ? " checked" : "") + ">";
    }
    var type = pref.widget === "number" ? "number" : "text";
    return '<input type="' + type + '" id="' + name + '" data-field="' + esc(pref.param) +
      '" value="' + esc(val == null ? "" : val) + '" placeholder="' + esc(pref.placeholder || "") + '">';
  }

  function renderNode(id) {
    var n = nodeById(id);
    if (!n) return;
    var e = entryFor(n.name);
    var mount = document.querySelector("#node-" + id + " .studio-node");
    if (!mount) return;
    var f = (n.data && n.data.fields) || {};

    // A block instance whose definition this canvas does not carry: draw it as a stub
    // rather than throwing, so one unknown block cannot take the whole graph down with it.
    if (!e) {
      mount.innerHTML = '<div class="node-head"><span>' + esc(n.name) +
        '</span><span class="node-del" data-role="del" title="Delete">✕</span></div>' +
        '<div class="node-body"><div class="block-tag">missing schema definition</div>' +
        "<p class=\"placeholder\">Insert “" + esc(blockNameOf(n.name)) +
        "” from the Schemas list to restore it.</p></div>";
      attachNode(id);
      return;
    }

    var html = '<div class="node-head"><span>' + esc(e.label) +
      '</span><span class="node-del" data-role="del" title="Delete">✕</span></div><div class="node-body">';

    if (e.special === "block_instance") {
      html += '<div class="block-tag">schema</div>';
    } else if (e.special === "block_in" || e.special === "block_out") {
      html += '<div class="block-tag">' +
        (e.special === "block_in" ? "what this schema takes in" : "what this schema hands back") +
        "</div>";
    }

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

    // Input ports. A Schema Outputs boundary types and titles each input from the wire on
    // it (the inner result it hands back); every other node reads its ports from the spec.
    if (e.special === "block_out") {
      boundaryInfo(id).forEach(function (o) {
        html += '<div class="port-in" data-role="bport-in"><span class="wire-badge" data-t="' + esc(o.type) +
          '">' + esc(o.type) + '</span> <span data-role="bname">' + esc(o.name) + "</span></div>";
      });
    } else {
      portSpecs(e, id).forEach(function (inp) {
        var badge = inp.wire === "csv"
          ? '<span class="wire-badge" data-t="csv">csv</span>'
          : '<span class="wire-badge" data-t="' + esc(inp.accepts[0]) + '" title="' + esc(inp.accepts.join(", ")) + '">' + esc(inp.accepts[0]) + "</span>";
        html += '<div class="port-in">' + badge + " " + esc(inp.label) + (inp.optional ? " <em>(opt)</em>" : "") + "</div>";
      });
    }
    // Variadic ± lives on the input side (Combine CSVs) or on a Schema Outputs boundary.
    if (e.variadic && e.variadic.side !== "output") {
      var count = portSpecs(e, id).length;
      var vlabel = e.special === "block_out" ? " outputs" : " inputs";
      html += '<div class="port-vary">' +
        '<button type="button" data-role="port-minus" title="Remove the last"' +
        (count <= e.variadic.min ? " disabled" : "") + ">−</button>" +
        '<span>' + count + vlabel + "</span>" +
        '<button type="button" data-role="port-plus" title="Add one"' +
        (count >= e.variadic.max ? " disabled" : "") + ">+</button></div>";
    }

    // Promoting a field exposes it as an argument on the schema currently being edited
    // (the checkbox only appears alongside that schema's own, untagged Schema Inputs
    // node -- never on a dependency region, which is read-only display).
    var blockInId = (n.data || {}).def_of ? null : ownBlockInNode();
    var promoted = blockInId ? ((nodeById(blockInId).data.fields || {}).promoted || []) : [];
    e.prefs.forEach(function (pref) {
      var promoteHtml = "";
      if (blockInId) {
        var checked = promoted.some(function (p) { return String(p.node) === String(id) && p.param === pref.param; });
        promoteHtml = '<label class="promote-toggle" title="Expose as an argument on this schema">' +
          '<input type="checkbox" data-role="promote" data-param="' + esc(pref.param) + '"' +
          (checked ? " checked" : "") + "><span>promote</span></label>";
      }
      html += '<div class="pref-row"><label>' + esc(pref.label) + "</label>" + promoteHtml + "</div>"
        + widgetHtml(id, pref, f);
    });

    // Output-name field (annotation new column / distillation csv / viz html)
    if (e.output && e.output.param && e.special !== "csv_input" && e.special !== "select_column") {
      var lbl = e.output.kind === "column" ? "New column" : (e.output.kind === "csv" ? "Output CSV" : "Output HTML");
      html += "<label>" + lbl + "</label><input type=\"text\" data-field=\"" + esc(e.output.param) +
        '" value="' + esc(f[e.output.param] == null ? e.output.default : f[e.output.param]) + '">';
    }

    // Output ports: a schema instance emits one per declared output, and a Schema Inputs
    // boundary one per input the schema takes -- each typed/titled from the wire on it.
    if (e.special === "block_instance" || e.special === "block_in") {
      var outs = e.special === "block_instance"
        ? (e.outputs || []).map(function (o) { return { name: o.name, type: o.type || "column" }; })
        : boundaryInfo(id);
      var role = e.special === "block_in" ? ' data-role="bport-out"' : "";
      var nameRole = e.special === "block_in" ? ' data-role="bname"' : "";
      outs.forEach(function (o) {
        html += '<div class="port-out"' + role + '><span' + nameRole + ">" + esc(o.name) + '</span> ' +
          '<span class="wire-badge" data-t="' + esc(o.type) + '">' + esc(o.type) + "</span></div>";
      });
      if (e.special === "block_in") {
        var inCount = Object.keys(n.outputs || {}).length;
        html += '<div class="port-vary port-vary-out">' +
          '<button type="button" data-role="outport-minus" title="Remove the last input"' +
          (inCount <= 0 ? " disabled" : "") + ">−</button>" +
          "<span>" + inCount + " inputs</span>" +
          '<button type="button" data-role="outport-plus" title="Add an input">+</button></div>';
      }
    } else if (e.category !== "visualization" && e.special !== "csv_input"
               && e.special !== "select_column" && e.special !== "block_out") {
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
    var n = nodeById(id);
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

    // Variadic ports: + appends one, − drops the last (and any wire into it, so a
    // connection never outlives the port it landed on).
    var plus = el.querySelector('[data-role="port-plus"]');
    if (plus) plus.addEventListener("click", function () {
      var node0 = nodeById(id);
      if (!node0) return;
      var entry = entryFor(node0.name);
      if (portSpecs(entry, id).length >= entry.variadic.max) return;
      editor.addNodeInput(id);
      renderNode(id);
      refreshAll();
      autosave();
    });
    var outPlus = el.querySelector('[data-role="outport-plus"]');
    if (outPlus) outPlus.addEventListener("click", function () {
      var node = nodeById(id);
      if (!node) return;
      if (Object.keys(node.outputs || {}).length >= 16) return;
      editor.addNodeOutput(id);
      var f = node.data.fields || (node.data.fields = {});
      f.labels = (f.labels || []).concat(["In " + (Object.keys(node.outputs).length)]);
      renderNode(id); refreshAll(); autosave();
    });
    var outMinus = el.querySelector('[data-role="outport-minus"]');
    if (outMinus) outMinus.addEventListener("click", function () {
      var node = nodeById(id);
      if (!node) return;
      var count = Object.keys(node.outputs || {}).length;
      if (count <= 0) return;                          // a schema may take no inputs at all
      editor.removeNodeOutput(id, "output_" + count);
      var f = node.data.fields || (node.data.fields = {});
      f.labels = (f.labels || []).slice(0, count - 1);
      renderNode(id); refreshAll(); autosave();
    });

    var minus = el.querySelector('[data-role="port-minus"]');
    if (minus) minus.addEventListener("click", function () {
      var node = nodeById(id);
      if (!node) return;
      var entry = entryFor(node.name);
      var count = Object.keys(node.inputs || {}).length;
      if (count <= entry.variadic.min) return;
      editor.removeNodeInput(id, "input_" + count);
      renderNode(id);
      refreshAll();
      autosave();
    });

    el.querySelectorAll("[data-field]").forEach(function (c) {
      var evt = (c.tagName === "SELECT" || c.type === "checkbox") ? "change" : "input";
      c.addEventListener(evt, function () { syncNode(id); refreshAll(); });
    });

    el.querySelectorAll('[data-role="promote"]').forEach(function (c) {
      c.addEventListener("change", function () {
        var blockInId = ownBlockInNode();
        var biNode = blockInId && nodeById(blockInId);
        if (!biNode) return;
        var fields = biNode.data.fields || (biNode.data.fields = {});
        var param = c.getAttribute("data-param");
        var list = (fields.promoted || []).filter(function (p) {
          return !(String(p.node) === String(id) && p.param === param);
        });
        if (c.checked) list.push({ node: String(id), param: param, name: param });
        fields.promoted = list;
        editor.updateNodeDataFromId(blockInId, biNode.data);
        autosave();
      });
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
    var n = nodeById(id);
    if (!n || (entryFor(n.name) || {}).special !== "select_column") return;
    var sel = document.querySelector("#node-" + id + ' [data-role="colpick"]');
    if (!sel) return;
    var prod = producerOf(id, 0);
    var prev = (n.data && n.data.column) || sel.value;
    sel.innerHTML = "";
    if (!prod) { sel.innerHTML = '<option value="">Connect a CSV…</option>'; return; }
    var cols = projectedColumns(prod, {}, producerPort(id, 0));
    // A saved column always stays on the menu, even when the upstream table does not exist
    // yet (a template that has not been Run). Dropping it would not just hide the setting:
    // the syncNode below would write the first option back over it.
    if (prev && !cols.some(function (c) { return c.name === prev; })) {
      cols = [{ name: prev, type: (n.data && n.data.type) || "text" }].concat(cols);
    }
    if (!cols.length) { sel.innerHTML = '<option value="">No columns…</option>'; return; }
    cols.forEach(function (c) {
      var o = document.createElement("option");
      o.value = c.name; o.textContent = c.name + "  (" + c.type + ")";
      sel.appendChild(o);
    });
    if (cols.some(function (c) { return c.name === prev; })) sel.value = prev;
    syncNode(id);
  }

  // A definition region is drawn as a frame behind the nodes that make up a block, so
  // a pipeline shows both what its blocks ARE and where they are used. The frame lives
  // in the precanvas, so it pans and zooms with the graph.
  // A definition region is a frame drawn tight around the nodes of one block. It is
  // measured from the live node boxes, so it shrinks to just contain them. When the
  // panel is hidden those boxes report zero, so we skip (and redraw on show) rather than
  // stamp a frame at the origin -- which is what made regions "reset" on tab switch.
  function drawRegions() {
    var pc = editor.precanvas;
    pc.querySelectorAll(".block-region").forEach(function (el) { el.remove(); });
    if (!container.offsetParent) return;
    var data = editor.drawflow.drawflow[editor.module].data;
    var groups = {};
    Object.keys(data).forEach(function (k) {
      var name = data[k].data && data[k].data.def_of;
      if (name) (groups[name] = groups[name] || []).push(data[k]);
    });
    Object.keys(groups).forEach(function (name) {
      var members = groups[name];
      var padX = 26, padTop = 46, padBottom = 22;
      var x0 = Math.min.apply(null, members.map(function (n) { return n.pos_x; })) - padX;
      var y0 = Math.min.apply(null, members.map(function (n) { return n.pos_y; })) - padTop;
      var x1 = Math.max.apply(null, members.map(function (n) {
        var el = document.getElementById("node-" + n.id);
        return n.pos_x + (el ? el.offsetWidth : 240);
      })) + padX;
      var y1 = Math.max.apply(null, members.map(function (n) {
        var el = document.getElementById("node-" + n.id);
        return n.pos_y + (el ? el.offsetHeight : 140);
      })) + padBottom;
      var frame = document.createElement("div");
      frame.className = "block-region";
      frame.style.left = x0 + "px";
      frame.style.top = y0 + "px";
      frame.style.width = (x1 - x0) + "px";
      frame.style.height = (y1 - y0) + "px";
      frame.innerHTML = '<span class="block-region-title">schema · ' + esc(name) + "</span>";
      pc.insertBefore(frame, pc.firstChild);
    });
  }

  // Re-layout the whole canvas without touching connections or parameters: the pipeline
  // in its own band, then one band per block definition beneath it. Within a band, nodes
  // flow left-to-right by dependency depth; a boundary or chart node is pinned to the
  // edge it belongs on and centred against the band. This is the "Reorganize" button, and
  // it also tidies a freshly grouped or inserted block so nothing lands off-screen.
  var COL_W = 300, ROW_H = 176, PAD_X = 60, PAD_Y = 56, BAND_GAP = 150;

  function layoutGraph() {
    var data = editor.drawflow.drawflow[editor.module].data;
    var ids = Object.keys(data);
    if (!ids.length) return;

    var bands = {};
    ids.forEach(function (id) {
      var band = (data[id].data && data[id].data.def_of) || " pipeline";
      (bands[band] = bands[band] || []).push(id);
    });
    var order = Object.keys(bands).sort();   // " pipeline" sorts first

    var cursorY = PAD_Y;
    order.forEach(function (band) {
      var members = bands[band];
      var inBand = {};
      members.forEach(function (id) { inBand[id] = true; });

      // longest-path depth over intra-band edges (the graph is a DAG)
      var depth = {};
      members.forEach(function (id) { depth[id] = 0; });
      for (var pass = 0; pass < members.length; pass++) {
        var moved = false;
        members.forEach(function (id) {
          var outs = data[id].outputs || {};
          Object.keys(outs).forEach(function (oc) {
            (outs[oc].connections || []).forEach(function (c) {
              if (inBand[c.node] && depth[c.node] < depth[id] + 1) {
                depth[c.node] = depth[id] + 1; moved = true;
              }
            });
          });
        });
        if (!moved) break;
      }
      var maxCol = Math.max.apply(null, members.map(function (id) { return depth[id]; }));
      members.forEach(function (id) {
        var name = data[id].name, e = entryFor(name);
        if (name === "__block_in__") depth[id] = 0;
        else if (name === "__block_out__") depth[id] = maxCol;
        else if (e && e.category === "visualization") depth[id] = maxCol;
      });

      // pack rows per column, keeping the current top-to-bottom order stable
      members.sort(function (a, b) { return (data[a].pos_y - data[b].pos_y) || (a > b ? 1 : -1); });
      var rowOfCol = {}, colCount = {};
      members.forEach(function (id) { colCount[depth[id]] = (colCount[depth[id]] || 0) + 1; });
      var maxRows = Math.max.apply(null, Object.keys(colCount).map(function (c) { return colCount[c]; }));
      members.forEach(function (id) {
        var col = depth[id];
        var row = rowOfCol[col] || 0; rowOfCol[col] = row + 1;
        // a lone boundary node sits centred against the tallest column, not at the top
        var offset = (colCount[col] === 1) ? Math.floor((maxRows - 1) / 2) : 0;
        data[id].pos_x = PAD_X + col * COL_W;
        data[id].pos_y = cursorY + (row + offset) * ROW_H;
      });
      cursorY += maxRows * ROW_H + BAND_GAP;
    });

    ids.forEach(function (id) {
      var el = document.getElementById("node-" + id);
      if (el) { el.style.left = data[id].pos_x + "px"; el.style.top = data[id].pos_y + "px"; }
      editor.updateConnectionNodes("node-" + id);
    });
    drawRegions();
    autosave();
  }

  // A definition region only earns its place on the canvas by being called: once the
  // last @Name instance disappears (deleted directly, or itself living inside a region
  // that just got pruned), remove its now-unused region too -- runs to a fixed point so
  // a chain of dependencies (A calls B calls C) cleans up all the way down in one pass.
  var pruneScheduled = false;
  function pruneUnusedDefinitions() {
    // refreshAll (which calls this) is itself one of Drawflow's own "nodeRemoved"
    // listeners, so this can run re-entrantly from inside editor.removeNodeId's own call
    // stack -- removing a node from there corrupts Drawflow's in-flight bookkeeping (see
    // nodeById's note on the same hazard). Defer the actual removal past the current
    // stack instead; refreshAll runs again once it lands, catching a dependency chain
    // (A used B used C) a pass at a time.
    if (pruneScheduled) return;
    pruneScheduled = true;
    setTimeout(function () {
      pruneScheduled = false;
      var data = editor.drawflow.drawflow[editor.module].data;
      var used = {};
      Object.keys(data).forEach(function (k) {
        if (data[k] && isInstance(data[k].name)) used[blockNameOf(data[k].name)] = true;
      });
      var removedAny = false;
      Object.keys(data).forEach(function (k) {
        var name = data[k] && data[k].data && data[k].data.def_of;
        if (name && !used[name] && nodeById(k)) { editor.removeNodeId("node-" + k); removedAny = true; }
      });
      Object.keys(BLOCKS).forEach(function (name) { if (!used[name]) delete BLOCKS[name]; });
      if (removedAny) refreshAll();
    }, 0);
  }

  function refreshAll() {
    pruneUnusedDefinitions();
    var ids = allNodeIds();
    // Every table the graph reads OR writes: a CSV Input's table, and the table each
    // importer/distillation node names as its output (which may already exist on disk,
    // and is then the only source of that node's column list).
    var csvs = ids.map(function (id) { return nodeById(id); })
      .filter(Boolean)
      .map(function (n) {
        var e = entryFor(n.name);
        if (!e) return "";
        if (e.special === "csv_input") return n.data.csv;
        if (e.output.kind !== "csv") return "";
        return ((n.data && n.data.fields) || {})[e.output.param] || e.output.default;
      }).filter(Boolean);
    Promise.all(csvs.map(ensureColumns)).then(function () {
      ids.forEach(function (id) { populateSelectColumn(id); updateOutLabel(id); updateBoundaryPorts(id); });
      drawRegions();
    });
  }

  // --------------------------------------------------------- create / drop
  function createNode(action, x, y) {
    var e = entryFor(action);
    if (!e) return;
    var inN = e.variadic ? e.variadic.min : e.inputs.length;
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
    if (!action) return;
    // Dropping a block from the palette drops an INSTANCE, and brings its definition onto
    // the canvas the first time the block is used here.
    if (isInstance(action)) { addBlockInstanceAt(blockNameOf(action), e.clientX, e.clientY); return; }
    addNodeAt(action, e.clientX, e.clientY);
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
    var tgt = nodeById(info.input_id);
    if (!tgt) return;
    var te = entryFor(tgt.name);
    if (!te) return;
    var inIdx = parseInt(info.input_class.split("_")[1], 10) - 1;
    var inp = portSpecs(te, info.input_id)[inIdx];
    if (!inp) return;

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
    if (inp.wire !== "any" && srcWire && srcWire !== inp.wire) {
      reject(info, "Expected a " + inp.wire + " wire, got " + srcWire + "."); return;
    }
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
  var pal = document.getElementById("studio-palette");

  function paletteItem(label, action, cat) {
    var item = document.createElement("div");
    item.className = "palette-item";
    item.setAttribute("data-cat", cat);
    item.setAttribute("draggable", "true");
    item.textContent = label;
    item.addEventListener("dragstart", function (ev) { ev.dataTransfer.setData("node", action); });
    return item;
  }

  (function buildPalette() {
    MANIFEST.palette.forEach(function (group) {
      var h = document.createElement("h4"); h.textContent = group.label; pal.appendChild(h);
      group.nodes.forEach(function (action) {
        pal.appendChild(paletteItem(MANIFEST.nodes[action].label, action, MANIFEST.nodes[action].category));
      });
    });
  })();

  // The user's saved blocks get their own palette section (block colour). Dragging one
  // drops an instance; the definition appears the first time the block is used here.
  var blockPaletteHead = null;
  function refreshBlockPalette(items) {
    var blocks = (items || []).filter(function (t) { return t.kind === "block"; });
    pal.querySelectorAll("[data-block-item]").forEach(function (el) { el.remove(); });
    if (blockPaletteHead) { blockPaletteHead.remove(); blockPaletteHead = null; }
    if (!blocks.length) return;
    blockPaletteHead = document.createElement("h4");
    blockPaletteHead.textContent = "Schemas";
    blockPaletteHead.setAttribute("data-block-item", "1");
    pal.appendChild(blockPaletteHead);
    blocks.forEach(function (b) {
      var item = paletteItem(b.name.replace(/_/g, " "), BLOCK_PREFIX + b.name, "block");
      item.setAttribute("data-block-item", "1");
      item.title = "in: " + (b.ports ? b.ports.inputs.join(", ") || "—" : "") +
                   "  ·  out: " + (b.ports ? b.ports.outputs.join(", ") || "—" : "");
      pal.appendChild(item);
    });
  }

  // ------------------------------------------------------- select & group
  // Shift-click builds a selection; "Group into block" turns it into a composite.
  var selection = {};

  function selectionIds() { return Object.keys(selection).filter(function (k) { return selection[k]; }); }

  function paintSelection() {
    Object.keys(editor.export().drawflow.Home.data).forEach(function (id) {
      var el = document.getElementById("node-" + id);
      if (el) el.classList.toggle("node-picked", !!selection[id]);
    });
    var btn = document.getElementById("group-block-btn");
    var hint = document.getElementById("selection-hint");
    var n = selectionIds().length;
    if (btn) btn.disabled = n < 1;
    if (hint) hint.textContent = n
      ? n + " node" + (n === 1 ? "" : "s") + " selected"
      : "Shift-click nodes to select them.";
  }

  function clearSelection() { selection = {}; paintSelection(); }

  container.addEventListener("click", function (ev) {
    var wrap = ev.target.closest(".drawflow-node");
    if (!wrap) { if (!ev.shiftKey) clearSelection(); return; }
    if (!ev.shiftKey) return;
    ev.preventDefault();
    var id = wrap.id.replace("node-", "");
    selection[id] = !selection[id];
    paintSelection();
  }, true);

  // Every block a set of nodes (transitively) instantiates, from the canvas' BLOCKS
  // cache -- what a saved schema must carry along so a nested instance's ports resolve
  // and the file stays runnable and portable on its own.
  function usedBlocks(nodes) {
    var out = {}, seen = {};
    function walk(list) {
      (list || []).forEach(function (n) {
        if (!isInstance(n.action) || seen[n.action]) return;
        seen[n.action] = 1;
        var block = BLOCKS[blockNameOf(n.action)];
        if (!block) return;
        out[blockNameOf(n.action)] = block;
        walk(block.body.nodes);
      });
    }
    walk(nodes);
    return out;
  }

  // Turn the selected nodes into a block: whatever crosses the selection boundary
  // becomes a port, so the block takes exactly what its insides could not supply and
  // hands back exactly what the rest of the pipeline was already using.
  function groupSelection() {
    var ids = selectionIds();
    if (!ids.length) return;
    var picked = {};
    ids.forEach(function (id) { picked[id] = true; });
    var data = editor.export().drawflow.Home.data;

    // A schema INSTANCE may be nested into a new outer schema (its own definition
    // travels along, gathered below); a definition REGION's internals may not -- group
    // the instance instead, not the expanded picture of what it does.
    if (ids.some(function (id) { return (data[id].data || {}).def_of; })) {
      flash("Ungroup a schema before grouping its insides into another one.");
      return;
    }

    var name = (prompt("Name this schema", "New Schema") || "").trim();
    if (!name) return;

    var inbound = [], outbound = [];
    ids.forEach(function (id) {
      var n = data[id];
      Object.keys(n.inputs || {}).forEach(function (inCls) {
        (n.inputs[inCls].connections || []).forEach(function (c) {
          if (!picked[String(c.node)]) {
            inbound.push({ outsideNode: String(c.node), outsidePort: parseInt(c.input.split("_")[1], 10) - 1,
                           insideNode: id, insidePort: parseInt(inCls.split("_")[1], 10) - 1 });
          }
        });
      });
      Object.keys(n.outputs || {}).forEach(function (outCls) {
        (n.outputs[outCls].connections || []).forEach(function (c) {
          if (!picked[String(c.node)]) {
            outbound.push({ insideNode: id, insidePort: parseInt(outCls.split("_")[1], 10) - 1,
                            outsideNode: String(c.node),
                            outsidePort: parseInt(c.output.split("_")[1], 10) - 1 });
          }
        });
      });
    });

    // one block input per distinct outside producer, one output per distinct inside result
    var inKey = function (e) { return e.outsideNode + ":" + e.outsidePort; };
    var outKey = function (e) { return e.insideNode + ":" + e.insidePort; };
    var inPorts = [], outPorts = [], seenIn = {}, seenOut = {};
    inbound.forEach(function (e) { if (!seenIn[inKey(e)]) { seenIn[inKey(e)] = inPorts.length; inPorts.push(e); } });
    outbound.forEach(function (e) { if (!seenOut[outKey(e)]) { seenOut[outKey(e)] = outPorts.length; outPorts.push(e); } });
    if (!outPorts.length) {
      // nothing leaves the selection: expose every inside result so the block is usable
      ids.forEach(function (id) {
        if (Object.keys(data[id].outputs || {}).length) {
          seenOut[id + ":0"] = outPorts.length;
          outPorts.push({ insideNode: id, insidePort: 0 });
        }
      });
    }

    // ---- build the definition graph (inner copies + the two boundary nodes)
    var defNodes = [], defEdges = [], remap = {}, next = 1;
    ids.forEach(function (id) { remap[id] = String(next++); });
    var inId = String(next++), outId = String(next++);
    ids.forEach(function (id) {
      var n = data[id];
      defNodes.push({ id: remap[id], action: n.name, csv: (n.data || {}).csv || "",
                      column: (n.data || {}).column || "", fields: (n.data || {}).fields || {},
                      ports: Object.keys(n.inputs || {}).length,
                      ports_out: Object.keys(n.outputs || {}).length });
      Object.keys(n.outputs || {}).forEach(function (outCls) {
        (n.outputs[outCls].connections || []).forEach(function (c) {
          if (picked[String(c.node)]) {
            defEdges.push({ from: remap[id], to: remap[String(c.node)],
                            toPort: parseInt(c.output.split("_")[1], 10) - 1,
                            fromPort: parseInt(outCls.split("_")[1], 10) - 1 });
          }
        });
      });
    });
    defNodes.push({ id: inId, action: "__block_in__", ports_out: Math.max(1, inPorts.length),
                    fields: { block: name, labels: inPorts.map(function (e, i) {
                      var ent = entryFor(data[e.insideNode].name);
                      var spec = ent ? portSpecs(ent, e.insideNode)[e.insidePort] : null;
                      return (spec && spec.label) || ("In " + (i + 1));
                    }), promoted: [] } });
    defNodes.push({ id: outId, action: "__block_out__", ports: Math.max(1, outPorts.length),
                    fields: { labels: outPorts.map(function (e, i) {
                      var o = resolveOutput(e.insideNode, {}, e.insidePort);
                      return (o && (o.column || o.csv)) || ("Out " + (i + 1));
                    }) } });
    inbound.forEach(function (e) {
      defEdges.push({ from: inId, to: remap[e.insideNode], toPort: e.insidePort,
                      fromPort: seenIn[inKey(e)] });
    });
    outPorts.forEach(function (e, i) {
      defEdges.push({ from: remap[e.insideNode], to: outId, toPort: i, fromPort: e.insidePort });
    });

    // ---- save the block as its own template, then rebuild the canvas around it
    // A nested @Name instance among defNodes brings its own definition along, so the
    // saved schema stays portable and its boundary types resolve rather than falling
    // back to "any" (see block_ops._port_type).
    var graph = studioToDrawflow(defNodes, defEdges);
    fetch(TEMPLATE_SAVE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      credentials: "same-origin",
      body: JSON.stringify({ name: name, is_block: true, graph: graph,
                             blocks: usedBlocks(defNodes), description: "Schema: " + name })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error || !d.block) { flash(d.error || "Could not save the schema."); return; }
      BLOCKS[d.name] = { header: d.block, body: { nodes: defNodes.filter(function (n) {
        return n.action !== "__block_in__" && n.action !== "__block_out__";
      }), edges: defEdges.filter(function (e) {
        return e.from !== inId && e.to !== inId && e.from !== outId && e.to !== outId;
      }) } };

      var box = ids.map(function (id) { return data[id]; });
      var px = Math.min.apply(null, box.map(function (n) { return n.pos_x; }));
      var py = Math.min.apply(null, box.map(function (n) { return n.pos_y; }));
      ids.forEach(function (id) { editor.removeNodeId("node-" + id); });

      var entry = entryFor(BLOCK_PREFIX + d.name);
      var instanceData = { action: BLOCK_PREFIX + d.name, csv: "", column: "", fields: {} };
      entry.prefs.forEach(function (p) { instanceData.fields[p.param] = p.default; });
      var newId = editor.addNode(BLOCK_PREFIX + d.name, entry.inputs.length,
        Math.max(1, (entry.outputs || []).length), px, py, "studio-node-wrap", instanceData,
        '<div class="studio-node" data-cat="block"></div>');
      renderNode(newId);

      inPorts.forEach(function (e, i) {
        editor.addConnection(e.outsideNode, newId, "output_" + (e.outsidePort + 1), "input_" + (i + 1));
      });
      outbound.forEach(function (e) {
        editor.addConnection(newId, e.outsideNode, "output_" + (seenOut[outKey(e)] + 1),
                             "input_" + (e.outsidePort + 1));
      });

      clearSelection();
      refreshTemplateList();
      refreshAll();
      layoutGraph();
      flash("Schema “" + d.name + "” saved and inserted.");
    }).catch(function () { flash("Network error saving the schema."); });
  }

  // The canvas speaks Drawflow; the grouping code above speaks the simple graph, so
  // convert here the same way the server does (ports, output count, edge ports).
  function studioToDrawflow(nodes, edges) {
    var out = { drawflow: { Home: { data: {} } } };
    nodes.forEach(function (n, idx) {
      var e = entryFor(n.action) || { category: "source", inputs: [], outputs: [] };
      var inN = n.ports != null ? n.ports : (e.inputs || []).length;
      var outN = n.ports_out != null ? n.ports_out : 1;
      var inputs = {}, outputs = {};
      for (var i = 0; i < inN; i++) inputs["input_" + (i + 1)] = { connections: [] };
      for (var j = 0; j < outN; j++) outputs["output_" + (j + 1)] = { connections: [] };
      out.drawflow.Home.data[n.id] = {
        id: n.id, name: n.action,
        data: { action: n.action, csv: n.csv || "", column: n.column || "", fields: n.fields || {} },
        class: "studio-node-wrap",
        html: '<div class="studio-node" data-cat="' + (e.category || "source") + '"></div>',
        typenode: false, inputs: inputs, outputs: outputs,
        pos_x: 60 + idx * 300, pos_y: 60 + (idx % 3) * 190
      };
    });
    edges.forEach(function (edge) {
      var src = out.drawflow.Home.data[edge.from], dst = out.drawflow.Home.data[edge.to];
      if (!src || !dst) return;
      var oc = "output_" + ((edge.fromPort || 0) + 1), ic = "input_" + ((edge.toPort || 0) + 1);
      if (!src.outputs[oc]) src.outputs[oc] = { connections: [] };
      if (!dst.inputs[ic]) dst.inputs[ic] = { connections: [] };
      src.outputs[oc].connections.push({ node: String(edge.to), output: ic });
      dst.inputs[ic].connections.push({ node: String(edge.from), input: oc });
    });
    return out;
  }

  // Insert a saved block: the pipeline takes a frozen copy of the definition (so it
  // stays runnable on its own), one instance node, and -- so the pipeline shows what
  // the block IS as well as where it is used -- the definition region itself.
  function drawflowToSimple(graph) {
    var out = { nodes: [], edges: [] };
    var data = graph.drawflow.Home.data;
    Object.keys(data).forEach(function (k) {
      var n = data[k];
      out.nodes.push({ id: String(n.id), action: n.name, csv: (n.data || {}).csv || "",
        column: (n.data || {}).column || "", fields: (n.data || {}).fields || {},
        ports: Object.keys(n.inputs || {}).length,
        ports_out: Object.keys(n.outputs || {}).length });
      Object.keys(n.outputs || {}).forEach(function (oc) {
        (n.outputs[oc].connections || []).forEach(function (c) {
          out.edges.push({ from: String(n.id), to: String(c.node),
            toPort: parseInt(c.output.split("_")[1], 10) - 1,
            fromPort: parseInt(oc.split("_")[1], 10) - 1 });
        });
      });
    });
    return out;
  }

  function regionPresent(name) {
    var data = editor.drawflow.drawflow[editor.module].data;
    return Object.keys(data).some(function (k) {
      return data[k].data && data[k].data.def_of === name;
    });
  }

  // The canvas' own (top-level, not def_of-tagged) Schema Inputs node, when the graph
  // open right now IS a schema's own definition -- opening a schema loads its boundary
  // nodes untagged (see the template-load handler), while a dependency it depends on is
  // drawn as a def_of-tagged region. So a node's fields are promote-able exactly when it
  // sits alongside this node: editing the schema itself, not looking at one it calls or
  // one it depends on.
  function ownBlockInNode() {
    var data = editor.drawflow.drawflow[editor.module].data;
    var id = Object.keys(data).find(function (k) {
      return data[k].name === "__block_in__" && !(data[k].data || {}).def_of;
    });
    return id || null;
  }

  // Draw a definition's nodes as a region tagged def_of=name. A no-op if already present.
  function placeDefinitionRegion(name, bodyNodes, bodyEdges) {
    if (regionPresent(name)) return;
    var idMap = {};
    bodyNodes.forEach(function (n) {
      var e = entryFor(n.action) || { category: "source", inputs: [] };
      // A body node coming straight from an embedded definition (rather than through
      // drawflowToSimple) carries `ports`/`ports_out` only when its author set them
      // explicitly (a variadic node) -- fall back to the manifest's declared count the
      // same way studioToDrawflow does, so a plain node is never given zero ports.
      var inN = n.ports != null ? n.ports : (e.inputs || []).length;
      var outN = n.ports_out != null ? n.ports_out : 1;
      var d = { action: n.action, csv: n.csv, column: n.column, fields: n.fields, def_of: name };
      idMap[n.id] = editor.addNode(n.action, inN, outN, 0, 0, "studio-node-wrap", d,
        '<div class="studio-node" data-cat="' + esc(e.category || "source") + '"></div>');
      renderNode(idMap[n.id]);
    });
    bodyEdges.forEach(function (e) {
      editor.addConnection(idMap[e.from], idMap[e.to],
        "output_" + ((e.fromPort || 0) + 1), "input_" + ((e.toPort || 0) + 1));
    });
  }

  // A definition's own body may itself instantiate further blocks; bring those in too,
  // depth first, so every BLOCKS entry a region's nodes need is known before that region
  // is drawn (entryFor resolves a @Name node from BLOCKS, not from the file it came from).
  // `pool` is the {name: {header, body}} this graph already embeds (graph.blocks) --
  // preferred over a network round trip, since a saved schema travels with everything
  // it is itself built from (see block_ops / usedBlocks).
  function addNestedDefinitions(bodyNodes, pool) {
    bodyNodes.forEach(function (n) {
      if (!isInstance(n.action)) return;
      var nested = blockNameOf(n.action);
      if (BLOCKS[nested] && regionPresent(nested)) return;
      var known = (pool || {})[nested];
      if (known) {
        BLOCKS[nested] = known;
        addNestedDefinitions(known.body.nodes, pool);
        placeDefinitionRegion(nested, known.body.nodes, known.body.edges);
      } else {
        ensureBlock(nested, function () { refreshAll(); });
      }
    });
  }

  // Bring a block's definition onto the canvas (its nodes tagged as a region) and record
  // the frozen copy this pipeline carries -- recursing into every schema it is itself
  // built from, so opening or inserting one shows its whole dependency chain.
  function addBlockDefinition(name, graph) {
    var simple = drawflowToSimple(graph);
    var boundary = {};
    simple.nodes.forEach(function (n) {
      if (n.action === "__block_in__" || n.action === "__block_out__") boundary[n.id] = true;
    });
    var bodyNodes = simple.nodes.filter(function (n) { return !boundary[n.id]; });
    var bodyEdges = simple.edges.filter(function (e) { return !boundary[e.from] && !boundary[e.to]; });
    BLOCKS[name] = { header: graph.block, body: { nodes: bodyNodes, edges: bodyEdges } };
    addNestedDefinitions(bodyNodes, graph.blocks || {});
    placeDefinitionRegion(name, bodyNodes, bodyEdges);
  }

  function addBlockInstance(name, x, y) {
    var entry = entryFor(BLOCK_PREFIX + name);
    if (!entry) return null;
    var instanceData = { action: BLOCK_PREFIX + name, csv: "", column: "", fields: {} };
    entry.prefs.forEach(function (p) { instanceData.fields[p.param] = p.default; });
    var id = editor.addNode(BLOCK_PREFIX + name, entry.inputs.length,
      Math.max(1, (entry.outputs || []).length), x, y, "studio-node-wrap",
      instanceData, '<div class="studio-node" data-cat="block"></div>');
    renderNode(id);
    return id;
  }

  // Fetch a block's definition if the canvas does not already carry it, then run `then`.
  function ensureBlock(name, then) {
    if (BLOCKS[name] && regionPresent(name)) { then(); return; }
    fetch(TEMPLATE_LOAD_URL.replace("__NAME__", encodeURIComponent(name)), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error || !d.graph || !d.graph.block) { flash(d.error || "Could not load schema."); return; }
        addBlockDefinition(name, d.graph);
        then();
      })
      .catch(function () { flash("Network error loading schema."); });
  }

  // Insert a block by name: a fresh definition region (first use) plus one instance,
  // then a tidy so nothing lands off-screen. Used by the dropdown and palette drag.
  function insertBlock(name, graph) {
    if (graph) addBlockDefinition(name, graph);
    ensureBlock(name, function () {
      addBlockInstance(name, 60, 60);
      refreshAll();
      layoutGraph();
      flash("Inserted schema “" + name.replace(/_/g, " ") + "”.");
    });
  }

  function addBlockInstanceAt(name, clientX, clientY) {
    var pc = editor.precanvas, rect = pc.getBoundingClientRect(), zoom = editor.zoom;
    var x = clientX * (pc.clientWidth / (pc.clientWidth * zoom)) - (rect.x * (pc.clientWidth / (pc.clientWidth * zoom)));
    var y = clientY * (pc.clientHeight / (pc.clientHeight * zoom)) - (rect.y * (pc.clientHeight / (pc.clientHeight * zoom)));
    var firstUse = !(BLOCKS[name] && regionPresent(name));
    ensureBlock(name, function () {
      addBlockInstance(name, x, y);
      refreshAll();
      if (firstUse) layoutGraph();        // place the newly-added definition sensibly
      autosave();
    });
  }

  var groupBtn = document.getElementById("group-block-btn");
  if (groupBtn) groupBtn.addEventListener("click", groupSelection);
  var tidyBtn = document.getElementById("tidy-btn");
  if (tidyBtn) tidyBtn.addEventListener("click", layoutGraph);

  // ------------------------------------------------------------------- run
  function compile() {
    var data = editor.export().drawflow.Home.data;
    var nodes = [], edges = [];
    Object.keys(data).forEach(function (k) {
      var n = data[k];
      nodes.push({ id: String(n.id), action: n.name, csv: (n.data && n.data.csv) || "",
        column: (n.data && n.data.column) || "", fields: (n.data && n.data.fields) || {},
        def_of: (n.data && n.data.def_of) || null,
        ports: Object.keys(n.inputs || {}).length,
        ports_out: Object.keys(n.outputs || {}).length });
      Object.keys(n.outputs || {}).forEach(function (outCls) {
        (n.outputs[outCls].connections || []).forEach(function (c) {
          edges.push({ from: String(n.id), to: String(c.node),
            toPort: parseInt(c.output.split("_")[1], 10) - 1,
            fromPort: parseInt(outCls.split("_")[1], 10) - 1 });
        });
      });
    });
    return { nodes: nodes, edges: edges, blocks: BLOCKS };
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
  var templateLoadBtn = document.getElementById("template-load-btn");
  var saveTemplateBtn = document.getElementById("save-template-btn");
  var clearBtn = document.getElementById("clear-canvas-btn");

  var TEMPLATE_KIND = {};
  var TEMPLATE_DESC = {};

  function refreshTemplateList() {
    if (!TEMPLATES_URL) return;
    fetch(TEMPLATES_URL, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var items = d.templates || [];
        refreshBlockPalette(items);
        TEMPLATE_KIND = {};
        TEMPLATE_DESC = {};
        items.forEach(function (t) {
          TEMPLATE_KIND[t.name] = t.kind || "pipeline";
          TEMPLATE_DESC[t.name] = t.kind === "block" && t.ports
            ? "(" + t.ports.inputs.length + " in / " + t.ports.outputs.length + " out)" +
              (t.description ? " — " + t.description : "")
            : (t.description || "");
        });
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
      body: JSON.stringify(function () {
        var graph = editor.export();
        graph.blocks = BLOCKS;
        return { name: name, description: description, graph: graph,
                 is_block: !!document.getElementById("save-as-block").checked };
      }())
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (!res.ok || res.data.error) { flash(res.data.error || "Could not save template."); return; }
        flash("Saved template “" + res.data.name + "”.");
        refreshTemplateList();
      })
      .catch(function () { flash("Network error saving template."); });
  });

  function loadTemplateByName(name) {
    fetch(TEMPLATE_LOAD_URL.replace("__NAME__", encodeURIComponent(name)), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error || !d.graph) { flash(d.error || "Could not load template."); return; }
        // Opening a template replaces the canvas -- a pipeline with its pipeline, and a
        // schema with its full definition (boundary nodes and all, no highlight region,
        // since here you are editing the schema itself, not calling it). To CALL a schema,
        // drag it from the Schemas palette; that drops an instance + its definition region.
        importGraph(d.graph);
        if (TEMPLATE_KIND[name] === "block" && d.graph.block) {
          var box = document.getElementById("save-as-block");
          if (box) box.checked = true;                 // so re-saving keeps it a schema
          // A schema's own file has no self-region (you are editing it, not calling it),
          // but it may itself be built from other schemas -- bring those in as regions
          // too, so the outline shows the whole dependency chain it depends on.
          var ownBody = drawflowToSimple(d.graph).nodes.filter(function (n) {
            return n.action !== "__block_in__" && n.action !== "__block_out__";
          });
          addNestedDefinitions(ownBody, d.graph.blocks || {});
          refreshAll();
          flash("Editing schema “" + d.name + "”. Re-save keeps it a schema; drag it from Schemas to use it.");
        } else if ((d.stale || []).length) {
          flash(d.stale.map(function (b) {
            return b.name + " is v" + b.used + "; the library has v" + b.available;
          }).join(" · "));
        }
      })
      .catch(function () { flash("Network error loading template."); });
  }

  if (templateLoadBtn) templateLoadBtn.addEventListener("click", function () {
    // Make sure TEMPLATE_KIND/TEMPLATE_DESC (block-vs-pipeline + port counts,
    // from the Studio's own manifest endpoint) are fresh before labelling rows.
    refreshTemplateList();
    var tree = (window.PortalFileTrees || {}).template || { folders: [], files: [], path: "" };
    window.openGroupedPicker("Load a template", [
      { label: "Templates", tree: tree,
        filter: function (f) { return (f.kinds || []).indexOf("json") !== -1; },
        render: function (f) {
          return f.name + (TEMPLATE_KIND[f.name] === "block" ? "  [schema]" : "");
        },
        sub: function (f) { return TEMPLATE_DESC[f.name] || f.description || ""; } },
    ]).then(function (picked) {
      if (picked) loadTemplateByName(picked.file.name);
    });
  });

  // Assistant bridge: the agent can save a pipeline server-side, so let it refresh
  // the Templates dropdown (and open a graph it just wrote) without a page reload.
  window.Studio = {
    refreshTemplates: refreshTemplateList,
    importGraph: importGraph,
    nodeForTest: nodeById,
    exportForTest: function () { return editor.drawflow.drawflow[editor.module].data; },
    // Drawping a connection needs the node's real screen box, and a hidden panel
    // reports zeros -- so every wire drawn (or recomputed) while the Studio tab was
    // inactive lands at the origin instead of on its port. Nudging a node used to be
    // the only way to fix it; the tab bar calls this the moment the panel is shown.
    redrawWires: function () {
      if (!container.offsetParent) return;          // still hidden: nothing to measure
      Object.keys(editor.drawflow.drawflow.Home.data).forEach(function (id) {
        editor.updateConnectionNodes("node-" + id);
      });
      drawRegions();                                // region frames were skipped while hidden
    },
    loadTemplate: function (name) {
      return fetch(TEMPLATE_LOAD_URL.replace("__NAME__", encodeURIComponent(name)), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error || !d.graph) throw new Error(d.error || "Could not load pipeline.");
          importGraph(d.graph);
          refreshTemplateList();
        });
    }
  };

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
    importGraph(saved, false);
  } else if (CSV_NAMES.length) {
    createNode("__csv__", 40, 60);
  }

  refreshTemplateList();

  // On a fresh page reload the Studio panel may already be the active tab, but no
  // tab click or popstate fires, so the tab bar never calls redrawWires -- the wires
  // restored above were drawn against a not-yet-laid-out (or still-hidden) canvas and
  // stay stamped at the origin until a template is loaded. Watch the container and the
  // first time it actually has a box, recompute every wire once. This also covers the
  // canvas being hidden at load (inactive tab): a display:none element reports 0x0 and
  // the observer fires again when the tab is shown and it gains a real size.
  (function primeWires() {
    function ready() { return container.offsetParent && container.offsetWidth; }
    function fire() { requestAnimationFrame(window.Studio.redrawWires); }
    if (ready()) { fire(); return; }
    if (typeof ResizeObserver === "undefined") return;
    var ro = new ResizeObserver(function () {
      if (!ready()) return;
      ro.disconnect();
      fire();
    });
    ro.observe(container);
  })();
})();
