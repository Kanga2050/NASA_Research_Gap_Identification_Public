/* ============================================================================
   Synthesize — a block editor for authoring research papers from your own
   charts and data. The editing canvas is the report itself: each block is a real
   report element (styled by synthesize.css, scoped `.synthesize-doc`) that you
   edit in place. On Build, the block model is POSTed to the server, which renders
   the same markup and embeds live Plotly charts into one self-contained HTML file.

   Block-model shape mirrors App/Servers/Paper_Builder.py (the authoritative
   renderer). Keep the two in lockstep.
   ========================================================================== */
(function () {
  "use strict";
  var root = document.getElementById("synthesize");
  if (!root) return;

  var CSRF = root.getAttribute("data-csrf");
  var USER = root.getAttribute("data-user") || "anon";
  var PAPERS_URL = root.getAttribute("data-papers-url");
  var SAVE_URL = root.getAttribute("data-paper-save-url");
  var BUILD_URL = root.getAttribute("data-paper-build-url");
  var LOAD_TMPL = root.getAttribute("data-paper-load-url");   // /papers/__NAME__/
  var HTML_TMPL = root.getAttribute("data-html-url");         // /outputs/html/__NAME__/
  var STORAGE_KEY = "synthesize:doc:" + USER;

  function readJSON(id, fallback) {
    var el = document.getElementById(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent); } catch (e) { return fallback; }
  }
  var CHARTS = readJSON("synthesize-charts", []) || [];
  var PAPERS = readJSON("synthesize-papers", []) || [];
  var MANIFEST = readJSON("studio-manifest", {}) || {};
  var CSVS = readJSON("studio-csvs", []) || [];
  var FUNCTIONS = Object.keys((MANIFEST && MANIFEST.nodes) || {});

  // ---- DOM handles ---------------------------------------------------------
  var page = document.getElementById("synth-page");
  var titleInput = document.getElementById("synth-title-input");
  var openSel = document.getElementById("synth-open");
  var statusEl = document.getElementById("synth-status");
  var sourcesList = document.getElementById("synth-sources-list");
  var inlineBar = document.getElementById("synth-inline-toolbar");

  // ---- State ---------------------------------------------------------------
  var doc = null;
  var currentName = null;

  function starterDoc() {
    return {
      title: "Untitled paper",
      blocks: [
        { type: "subtitle", html: "" },
        { type: "heading", num: "1", text: "Introduction" },
        { type: "paragraph", variant: "lead", html: "" }
      ],
      sources: []
    };
  }

  // ---- Small utils ---------------------------------------------------------
  function escText(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function escAttr(s) {
    return escText(s).replace(/"/g, "&quot;");
  }
  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "synth-status" + (kind ? " " + kind : "");
  }
  function nameTmpl(tmpl, name) {
    return tmpl.replace("__NAME__", encodeURIComponent(name));
  }
  // Local draft. Stores the open paper's filename alongside the doc so a reload
  // mid-edit comes back still bound to that file — otherwise Save would have no
  // name to overwrite and would fork a second paper off the title.
  var saveTimer = null;
  function autosave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ name: currentName, doc: doc }));
      } catch (e) {}
    }, 400);
  }
  function readDraft() {
    var raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch (e) { return null; }
    if (!raw) return null;
    // Drafts written before the draft grew a `name` were the bare doc.
    if (raw.blocks) return { name: null, doc: raw };
    return (raw.doc && raw.doc.blocks) ? { name: raw.name || null, doc: raw.doc } : null;
  }

  // The paper's filename is fixed once it exists: whatever it was opened/saved as,
  // falling back to a slug of the title for a paper that has never been saved. Save
  // overwrites it in place — no "save as" prompt, no second copy.
  function docName() {
    return currentName || slug(doc.title) || "Untitled_paper";
  }

  // ---- Inline HTML sanitiser (read-back from contenteditable) --------------
  var ALLOWED = { B: 1, I: 1, SUP: 1, SPAN: 1, A: 1, BR: 1 };
  function cleanNode(node) {
    var out = "";
    node.childNodes.forEach(function (ch) {
      if (ch.nodeType === 3) { out += escText(ch.nodeValue); return; }
      if (ch.nodeType !== 1) return;
      // Editor chrome living inside an editable (the ✕ handles, the figure picker)
      // is not part of the text — drop the whole subtree rather than its letters.
      if (ch.getAttribute("contenteditable") === "false") return;
      var tag = ch.tagName;
      if (tag === "STRONG") tag = "B";
      if (tag === "EM") tag = "I";
      if (tag === "BR") { out += "<br>"; return; }
      if (tag === "DIV" || tag === "P") { out += cleanNode(ch); return; }
      if (!ALLOWED[tag]) { out += cleanNode(ch); return; }
      var attrs = "";
      if (tag === "A") {
        var href = ch.getAttribute("href") || "";
        if (/^javascript:/i.test(href)) href = "#";
        attrs = ' href="' + escAttr(href) + '"';
      } else if (tag === "SPAN") {
        if (!/(^|\s)tag(\s|$)/.test(ch.className)) { out += cleanNode(ch); return; }
        attrs = ' class="tag"';
      } else if (tag === "SUP") {
        if (!/(^|\s)r(\s|$)/.test(ch.className)) { out += cleanNode(ch); return; }
        attrs = ' class="r"';
      }
      var lc = tag.toLowerCase();
      out += "<" + lc + attrs + ">" + cleanNode(ch) + "</" + lc + ">";
    });
    return out;
  }
  function cleanInline(html) {
    var tpl = document.createElement("div");
    tpl.innerHTML = html;
    return cleanNode(tpl).trim();
  }

  // ---- Field path get/set (e.g. "items:1:value", "paras:0", "rows:2:3") ----
  function setField(block, path, value) {
    var segs = path.split(":");
    var o = block;
    for (var i = 0; i < segs.length - 1; i++) {
      var k = /^\d+$/.test(segs[i]) ? +segs[i] : segs[i];
      o = o[k];
      if (o == null) return;
    }
    var last = segs[segs.length - 1];
    last = /^\d+$/.test(last) ? +last : last;
    // Table cells are objects {html,cls}; write into .html, keep the class.
    if (o[last] && typeof o[last] === "object" && "html" in o[last]) {
      o[last].html = value;
    } else {
      o[last] = value;
    }
  }

  // ========================================================================
  //  RENDER — model -> DOM.  Each block wrapped in .synth-block; text parts
  //  are contenteditable with a data-field path back into the model.
  // ========================================================================
  function ed(field, cls, placeholder, html) {
    return '<' + (cls === "b" ? "b" : "span") + ' class="synth-ed"'
      + ' contenteditable="true" data-field="' + escAttr(field) + '"'
      + (placeholder ? ' data-placeholder="' + escAttr(placeholder) + '"' : "")
      + '>' + (html || "") + '</' + (cls === "b" ? "b" : "span") + '>';
  }

  /* Heading numbers are derived, never typed: headings count 1, 2, 3… and each
     sub-heading is numbered inside its parent (2.1, 2.2, …), with the sub-counter
     resetting at every heading. Insert or delete a section and everything after it
     renumbers itself. Mirrors Paper_Builder.assign_numbers so the canvas and the
     built report always show the same numbers. `unnumbered: true` opts a heading out. */
  function assignNumbers() {
    var h = 0, s = 0;
    doc.blocks.forEach(function (b) {
      if (b.type === "heading") {
        if (b.unnumbered) { b.num = ""; return; }
        h += 1; s = 0; b.num = String(h);
      } else if (b.type === "subheading") {
        if (b.unnumbered || h === 0) { b.num = ""; return; }
        s += 1; b.num = h + "." + s;
      }
    });
  }
  /* A delete handle for one item *inside* a block — a list item, a paragraph of an
     abstract/callout, a byline field, a table row or column — the small-scale twin of
     the section 🗑. `path` is where the item lives in the model ("items:2", "paras:0",
     "rows:3", "cols:1"). It renders inside the item's own editable element, so it must
     be contenteditable="false" (cleanNode drops it on read-back) and absolutely
     positioned (synthesize.css) — nothing in the paper may shift when it appears. */
  function delBtn(path, title) {
    return '<button type="button" class="synth-x" contenteditable="false" tabindex="-1"'
      + ' data-del="' + escAttr(path) + '" title="' + escAttr(title) + '">&#10005;</button>';
  }

  function numSpan(b) {
    return b.num ? '<span class="num" contenteditable="false">' + escText(b.num) + '</span> ' : "";
  }

  function figureNumber(idx) {
    var n = 0;
    for (var i = 0; i <= idx; i++) if (doc.blocks[i] && doc.blocks[i].type === "figure") n++;
    return n;
  }

  function blockInner(b, idx) {
    switch (b.type) {
      case "subtitle":
        return '<div class="subtitle" contenteditable="true" data-field="html" '
          + 'data-placeholder="Subtitle / deck">' + (b.html || "") + '</div>';
      case "byline": {
        var items = (b.items || []).map(function (it, i) {
          return '<span>' + delBtn("items:" + i, "Delete this field")
            + '<b>' + ed("items:" + i + ":label", "s", "Label", escText(it.label))
            + ':</b> ' + ed("items:" + i + ":value", "s", "value", it.value || "") + '</span>';
        }).join("");
        return '<div class="byline">' + items + '</div>'
          + editRow('<button data-act="byline-add">+ field</button>');
      }
      case "interactive":
        return '<div class="interactive"><span style="font-size:18px">&#10035;</span>'
          + '<span contenteditable="true" data-field="html" data-placeholder="Interactive banner text">'
          + (b.html || "") + '</span></div>';
      case "abstract": {
        var paras = (b.paras || []).map(function (p, i) {
          return '<p contenteditable="true" data-field="paras:' + i + '" '
            + 'data-placeholder="Abstract paragraph">'
            + delBtn("paras:" + i, "Delete this paragraph") + (p || "") + '</p>';
        }).join("");
        return '<div class="abstract"><div class="abstract-h">Abstract</div>' + paras + '</div>'
          + editRow('<button data-act="abstract-add">+ paragraph</button>');
      }
      case "keywords":
        return '<p class="kw"><b>Keywords:</b> '
          + '<span contenteditable="true" data-field="html" data-placeholder="kw · kw · kw">'
          + (b.html || "") + '</span></p>';
      // Headings: the number is derived from document order (see assignNumbers) and is
      // NOT editable; the title is its own box, so you edit the words without ever
      // touching the numbering.
      case "heading":
        return '<h2>' + numSpan(b)
          + '<span class="synth-h-title" contenteditable="true" data-field="text" '
          + 'data-placeholder="Section heading">' + escText(b.text) + '</span></h2>';
      case "subheading":
        return '<h3>' + numSpan(b)
          + '<span class="synth-h-title" contenteditable="true" data-field="text" '
          + 'data-placeholder="Sub-section heading">' + escText(b.text) + '</span>'
          + (b.tag
            ? ' <span class="tag synth-h-tag" contenteditable="true" data-field="tag">'
              + escText(b.tag) + '</span>'
            : '')
          + '</h3>';
      case "paragraph":
        return '<p' + (b.variant === "lead" ? ' class="lead"' : '') + ' contenteditable="true" '
          + 'data-field="html" data-placeholder="Write a paragraph… (select text for bold / italic / cite)">'
          + (b.html || "") + '</p>';
      case "figure": {
        var n = figureNumber(idx);
        var h = b.height || 500;
        var opts = '<option value="">— choose a chart —</option>' + CHARTS.map(function (c) {
          return '<option value="' + escAttr(c) + '"' + (c === b.chart ? " selected" : "") + '>'
            + escText(c) + '</option>';
        }).join("");
        var picker = '<div class="fig-picker" contenteditable="false">'
          + '<select data-fig-select>' + opts + '</select>'
          + '<label>h<input type="number" data-fig-height value="' + h + '" min="180" max="1200" step="20" style="width:64px"></label>'
          + '</div>';
        var preview = b.chart
          ? '<iframe class="fig-preview" src="' + nameTmpl(HTML_TMPL, b.chart) + '" '
            + 'style="height:' + h + 'px" loading="lazy"></iframe>'
          : '<div class="fig-empty">Pick one of your charts to preview it here</div>';
        var cap = '<figcaption><span class="figtag">Figure&nbsp;' + n + ' &middot; interactive'
          + (b.new ? ' &middot; new' : '') + '</span> '
          + ed("headline", "b", "Headline.", b.headline || "") + ' '
          + '<span contenteditable="true" data-field="caption" data-placeholder="Caption text">'
          + (b.caption || "") + '</span></figcaption>';
        return '<figure' + (b.chart ? '' : ' class="no-chart"') + '>' + picker + preview + cap + '</figure>';
      }
      case "callout": {
        var vcls = (b.variant === "key" || b.variant === "danger") ? " " + b.variant : "";
        // A callout's body is `paras` (one string per paragraph), like the builder's.
        var cbody = (b.paras || []).map(function (p, i) {
          return '<p contenteditable="true" data-field="paras:' + i + '" '
            + 'data-placeholder="Callout body">'
            + delBtn("paras:" + i, "Delete this paragraph") + (p || "") + '</p>';
        }).join("");
        return '<div class="callout' + vcls + '">'
          + '<div class="callout-h" contenteditable="true" data-field="title" data-placeholder="Callout title">'
          + escText(b.title) + '</div>' + cbody + '</div>'
          + editRow('<button data-act="paras-add">+ paragraph</button>');
      }
      case "table": {
        // Each header cell carries the handle that deletes its whole column; the first
        // cell of each row carries the handle that deletes the row.
        var head = (b.head || []).map(function (h, c) {
          return '<th contenteditable="true" data-field="head:' + c + '">'
            + delBtn("cols:" + c, "Delete this column") + escText(h) + '</th>';
        }).join("");
        var rows = (b.rows || []).map(function (row, r) {
          var cells = row.map(function (cell, c) {
            var val = (cell && typeof cell === "object") ? (cell.html || "") : escText(cell);
            var cls = (cell && typeof cell === "object" && cell.cls) ? ' class="' + escAttr(cell.cls) + '"' : "";
            return '<td' + cls + ' contenteditable="true" data-field="rows:' + r + ':' + c + '">'
              + (c === 0 ? delBtn("rows:" + r, "Delete this row") : "") + val + '</td>';
          }).join("");
          return '<tr>' + cells + '</tr>';
        }).join("");
        return '<table><thead><tr>' + head + '</tr></thead><tbody>' + rows + '</tbody></table>'
          + editRow('<button data-act="row-add">+ row</button><button data-act="col-add">+ column</button>');
      }
      case "list": {
        var items = (b.items || []).map(function (it, i) {
          return '<li contenteditable="true" data-field="items:' + i + '" data-placeholder="List item">'
            + delBtn("items:" + i, "Delete this item") + (it || "") + '</li>';
        }).join("");
        return '<ul class="tight">' + items + '</ul>'
          + editRow('<button data-act="li-add">+ item</button>');
      }
      case "divider":
        return '<hr class="soft">';
      case "references": {
        var entries = (doc.sources || []).map(function (s, i) {
          return '<li id="r' + (i + 1) + '">' + refText(s) + '</li>';
        }).join("");
        return '<h3>References</h3><ol class="refs">' + entries + '</ol>'
          + editRow('<span style="color:#8a94a3">Edit entries in the Sources panel →</span>');
      }
      case "footnote":
        return '<p class="footnote" contenteditable="true" data-field="html" '
          + 'data-placeholder="Footnote / reproducibility note">' + (b.html || "") + '</p>';
      default:
        return '<div style="color:#b91c1c">Unknown block: ' + escText(b.type) + '</div>';
    }
  }

  function editRow(inner) {
    return '<div class="synth-table-tools" contenteditable="false">' + inner + '</div>';
  }

  function refText(s) {
    if (s.text) return s.text;
    var parts = [];
    if (s.authors) parts.push(escText(s.authors) + ",");
    if (s.title) parts.push("&ldquo;" + escText(s.title) + "&rdquo;,");
    if (s.journal) parts.push("<i>" + escText(s.journal) + "</i>");
    if (s.year) parts.push(escText(s.year) + (s.url ? "," : "."));
    if (s.url) {
      var link = s.doi ? "doi:" + escText(s.doi) : escText(s.url);
      parts.push('<a href="' + escAttr(s.url) + '">' + link + "</a>.");
    }
    return parts.join(" ").trim();
  }

  function render() {
    assignNumbers();
    titleInput.value = doc.title || "";
    page.innerHTML = "";
    // The paper's <h1>, editable in place (the builder emits it from doc.title too).
    var h1 = document.createElement("h1");
    h1.setAttribute("contenteditable", "true");
    h1.setAttribute("data-doc-title", "");
    h1.setAttribute("data-placeholder", "Paper title");
    h1.textContent = doc.title || "";
    page.appendChild(h1);
    doc.blocks.forEach(function (b, idx) {
      page.appendChild(gapEl(idx));
      var wrap = document.createElement("div");
      wrap.className = "synth-block";
      wrap.setAttribute("data-idx", idx);
      wrap.innerHTML = blockInner(b, idx) + blockTools(b);
      page.appendChild(wrap);
    });
    page.appendChild(gapEl(doc.blocks.length));   // trailing gap, so you can append at the end
    markAllEmpty();
    renderSources();
    autosave();
  }

  /* An insertion point between two sections. The gap is a zero-height,
     self-collapsing box, so adjacent block margins still collapse through it and
     the page keeps the exact spacing of the built report. Its affordance (rule +
     "+" button) is absolutely positioned and transparent until hovered — so at
     rest the gap is plain white and the canvas looks exactly like the paper. */
  function gapEl(i) {
    var g = document.createElement("div");
    g.className = "synth-gap";
    g.setAttribute("data-gap", i);
    g.innerHTML = '<div class="synth-gap-inner">'
      + '<span class="synth-gap-line"></span>'
      + '<button type="button" class="synth-gap-btn" title="Add a section here">+</button>'
      + '<span class="synth-gap-line"></span></div>';
    return g;
  }

  function blockTools(b) {
    // A sub-heading with no pill yet gets an "add tag" button here rather than an
    // empty inline pill, so an untagged sub-heading looks exactly like the paper's.
    var tagBtn = (b && b.type === "subheading" && !b.tag)
      ? '<button data-tool="tag" title="Add a tag pill">＋tag</button>' : "";
    return '<div class="synth-block-tools" contenteditable="false">'
      + '<button class="synth-drag" data-tool="drag" title="Drag to reorder" draggable="true">⠿</button>'
      + tagBtn
      + '<button data-tool="up" title="Move up">↑</button>'
      + '<button data-tool="down" title="Move down">↓</button>'
      + '<button class="danger" data-tool="del" title="Delete section">🗑</button>'
      + '</div>';
  }

  // ========================================================================
  //  Sources panel
  // ========================================================================
  function renderSources() {
    if (!doc.sources) doc.sources = [];
    sourcesList.innerHTML = "";
    doc.sources.forEach(function (s, i) {
      var hasText = !!(s.text && s.text.trim());
      var row = document.createElement("div");
      row.className = "synth-source-row";
      row.setAttribute("data-si", i);
      row.innerHTML =
        '<div class="synth-source-head"><span class="synth-source-n">[' + (i + 1) + ']</span>'
        + '<span class="synth-source-cite">cite → sup ' + (i + 1) + '</span></div>'
        + '<textarea data-src-field="text" rows="3" placeholder="Full citation — HTML allowed '
        + '(&lt;i&gt;, &lt;a href&gt;). Leave empty to compose from the fields below.">'
        + escText(s.text || "") + '</textarea>'
        + '<details class="synth-src-fields"' + (hasText ? "" : " open") + '>'
        + '<summary>Compose from fields' + (hasText ? " (ignored — full citation is set)" : "") + '</summary>'
        + srcInput(i, "authors", "Authors", s.authors)
        + srcInput(i, "title", "Title", s.title)
        + srcInput(i, "journal", "Journal", s.journal)
        + srcInput(i, "year", "Year", s.year)
        + srcInput(i, "url", "URL", s.url)
        + srcInput(i, "doi", "DOI", s.doi)
        + '</details>'
        + '<div class="synth-src-actions">'
        + '<button class="btn-secondary" data-src-up>↑</button>'
        + '<button class="btn-secondary" data-src-down>↓</button>'
        + '<button class="btn-secondary" data-src-del>Remove</button></div>';
      sourcesList.appendChild(row);
    });
  }
  function srcInput(i, field, ph, val) {
    return '<input data-src-field="' + field + '" placeholder="' + ph + '" value="'
      + escAttr(val || "") + '">';
  }

  // ========================================================================
  //  Add-section palette
  // ========================================================================
  var ADD_ITEMS = [
    ["heading", "Header", function () { return { type: "heading", text: "New section" }; }],
    ["subheading", "Sub-header", function () { return { type: "subheading", text: "New subsection", tag: "" }; }],
    ["paragraph", "Paragraph", function () { return { type: "paragraph", variant: "normal", html: "" }; }],
    ["lead", "Lead ¶", function () { return { type: "paragraph", variant: "lead", html: "" }; }],
    ["figure", "Figure", function () { return { type: "figure", chart: "", alt: "", headline: "", caption: "", height: 500, new: false }; }],
    ["callout", "Callout", function () { return { type: "callout", variant: "", title: "Note", paras: [""] }; }],
    ["key", "Key box", function () { return { type: "callout", variant: "key", title: "Why this matters", paras: [""] }; }],
    ["danger", "Danger box", function () { return { type: "callout", variant: "danger", title: "The key point", paras: [""] }; }],
    ["table", "Table", function () { return { type: "table", head: ["Column A", "Column B"], rows: [["", ""], ["", ""]] }; }],
    ["list", "List", function () { return { type: "list", items: [""] }; }],
    ["divider", "Divider", function () { return { type: "divider" }; }],
    ["references", "References", function () { return { type: "references" }; }],
    ["subtitle", "Subtitle", function () { return { type: "subtitle", html: "" }; }],
    ["byline", "Byline", function () { return { type: "byline", items: [{ label: "Analysis", value: "" }] }; }],
    ["abstract", "Abstract", function () { return { type: "abstract", paras: [""] }; }],
    ["keywords", "Keywords", function () { return { type: "keywords", html: "" }; }],
    ["banner", "Banner", function () { return { type: "interactive", html: "Every figure in this report is a <b>live, interactive Plotly chart</b> — hover, zoom, pan." }; }],
    ["footnote", "Footnote", function () { return { type: "footnote", html: "" }; }]
  ];
  // Insert a new block AT `at` (the gap index the "+" was clicked on).
  function addBlock(key, at) {
    for (var i = 0; i < ADD_ITEMS.length; i++) {
      if (ADD_ITEMS[i][0] !== key) continue;
      syncFromDom();
      if (at == null || at < 0 || at > doc.blocks.length) at = doc.blocks.length;
      doc.blocks.splice(at, 0, ADD_ITEMS[i][2]());
      render();
      var wrap = page.querySelector('.synth-block[data-idx="' + at + '"]');
      if (wrap) {
        wrap.scrollIntoView({ behavior: "smooth", block: "center" });
        var editable = wrap.querySelector('[contenteditable="true"]');
        if (editable) editable.focus();
      }
      return;
    }
  }

  // The "+" between sections opens this menu of section types.
  function openAddMenu(at, anchor) {
    closePopover();
    var gap = anchor.closest(".synth-gap");
    if (gap) gap.classList.add("open");
    popover = document.createElement("div");
    popover.className = "synth-popover synth-add-pop";
    popover.innerHTML = '<div class="synth-add-menu">' + ADD_ITEMS.map(function (it) {
      return '<button type="button" data-add="' + it[0] + '">' + escText(it[1]) + '</button>';
    }).join("") + '</div>';
    document.body.appendChild(popover);
    var r = anchor.getBoundingClientRect();
    var top = r.bottom + 6;
    var left = Math.max(8, Math.min(r.left - 110, window.innerWidth - 280));
    popover.style.left = left + "px";
    popover.style.top = top + "px";
    // Flip above if it would overflow the viewport bottom.
    var pr = popover.getBoundingClientRect();
    if (pr.bottom > window.innerHeight - 8) {
      popover.style.top = Math.max(8, r.top - pr.height - 6) + "px";
    }
    popover.addEventListener("click", function (e) {
      var key = e.target.getAttribute && e.target.getAttribute("data-add");
      if (!key) return;
      closePopover();
      addBlock(key, at);
    });
  }

  // ========================================================================
  //  Event wiring
  // ========================================================================
  function blockIndexOf(el) {
    var w = el.closest ? el.closest(".synth-block") : null;
    return w ? +w.getAttribute("data-idx") : -1;
  }

  // Inline edits -> model (no re-render, keeps the caret)
  page.addEventListener("input", function (e) {
    var el = e.target;
    if (!el.getAttribute) return;
    if (el.hasAttribute("data-doc-title")) {      // the in-canvas <h1>
      doc.title = el.textContent;
      titleInput.value = doc.title;
      autosave();
      return;
    }
    var field = el.getAttribute("data-field");
    var idx = blockIndexOf(el);
    if (field == null || idx < 0) return;
    var val = isRichEl(el) ? cleanInline(el.innerHTML) : el.textContent;
    setField(doc.blocks[idx], field, val);
    markEmpty(el);
    autosave();
  });

  // Which editables carry inline markup (bold/italic/tag/citation) vs plain text.
  function isRichEl(el) {
    return (el.tagName === "P" || el.classList.contains("subtitle")
      || el.tagName === "SPAN" || el.tagName === "B" || el.tagName === "LI"
      || el.tagName === "TD" || el.tagName === "TH"
      || el.classList.contains("callout-h"));
  }

  // Enter inside single editables: don't create block splits.
  page.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || e.shiftKey) return;
    var el = e.target;
    if (el.getAttribute && el.getAttribute("contenteditable") === "true") {
      // In a list item / a paragraph of an abstract or callout, Enter opens a fresh one
      // right below the one you're in; everywhere else it does nothing (a block is a
      // block — you split the paper with the "+" between sections).
      var idx = blockIndexOf(el);
      var m = /^(items|paras):(\d+)$/.exec(el.getAttribute("data-field") || "");
      e.preventDefault();
      if (idx < 0 || !m) return;
      var key = m[1], at = +m[2] + 1;
      syncFromDom();
      doc.blocks[idx][key].splice(at, 0, "");
      render();
      focusField(idx, key + ":" + at);
    }
  });

  // Backspace in an already-empty list item / paragraph removes it and joins the caret
  // to the one above — the keyboard twin of its ✕ handle. The last remaining item stays
  // (delete the section itself with its 🗑), so you can never backspace a block away.
  page.addEventListener("keydown", function (e) {
    if (e.key !== "Backspace") return;
    var el = e.target;
    if (!el.getAttribute || el.getAttribute("contenteditable") !== "true") return;
    var m = /^(items|paras):(\d+)$/.exec(el.getAttribute("data-field") || "");
    if (!m || plainText(el)) return;
    var idx = blockIndexOf(el);
    if (idx < 0) return;
    var arr = doc.blocks[idx][m[1]];
    if (!arr || arr.length <= 1) return;
    e.preventDefault();
    syncFromDom();
    var n = +m[2];
    arr.splice(n, 1);
    render();
    focusEnd(idx, m[1] + ":" + Math.max(0, n - 1));
  });

  // The editable's text with the editor chrome (its ✕ handle) excluded.
  function plainText(el) {
    return cleanInline(el.innerHTML).replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim();
  }
  // An item holding a ✕ handle is never CSS-:empty, so its placeholder is driven by a
  // class instead. Keep it in step with the text.
  function markEmpty(el) {
    if (el.hasAttribute("data-placeholder")) el.classList.toggle("is-empty", !plainText(el));
  }
  function markAllEmpty() {
    page.querySelectorAll('[contenteditable="true"][data-placeholder]').forEach(markEmpty);
  }

  // Pull every editable's current value into the model (before a structural re-render).
  function syncFromDom() {
    var titleEl = page.querySelector("[data-doc-title]");
    if (titleEl) doc.title = titleEl.textContent;
    page.querySelectorAll('[data-field]').forEach(function (el) {
      var idx = blockIndexOf(el);
      var field = el.getAttribute("data-field");
      if (idx < 0 || field == null || !doc.blocks[idx]) return;
      setField(doc.blocks[idx], field, isRichEl(el) ? cleanInline(el.innerHTML) : el.textContent);
    });
  }
  function fieldEl(idx, field) {
    return page.querySelector('.synth-block[data-idx="' + idx + '"] [data-field="' + CSS.escape(field) + '"]');
  }
  function focusField(idx, field) {
    var el = fieldEl(idx, field);
    if (el) el.focus();
  }
  function focusEnd(idx, field) {
    var el = fieldEl(idx, field);
    if (!el) return;
    el.focus();
    var r = document.createRange();
    r.selectNodeContents(el);
    r.collapse(false);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }

  // Clicks: block tools, figure picker, per-block add buttons
  page.addEventListener("click", function (e) {
    var t = e.target;
    // "+" between sections -> open the add-section menu at that insertion point
    var gapBtn = t.closest ? t.closest(".synth-gap-btn") : null;
    if (gapBtn) {
      var gap = gapBtn.closest(".synth-gap");
      openAddMenu(+gap.getAttribute("data-gap"), gapBtn);
      return;
    }
    // ✕ on an item inside a block: a list item, a paragraph, a byline field, a table
    // row or column. Deleting the last one leaves the block empty (its "+" tool adds
    // another) — to remove the block itself, use the section 🗑.
    var del = t.getAttribute && t.getAttribute("data-del");
    if (del) {
      var di = blockIndexOf(t);
      if (di < 0) return;
      syncFromDom();
      var blk = doc.blocks[di];
      var kind = del.split(":")[0], n = +del.split(":")[1];
      if (itemText(blk, kind, n) && !confirm("Delete this " + itemNoun(blk, kind) + "?")) return;
      if (kind === "cols") { blk.head.splice(n, 1); (blk.rows || []).forEach(function (r) { r.splice(n, 1); }); }
      else if (kind === "rows") blk.rows.splice(n, 1);
      else if (kind === "paras") blk.paras.splice(n, 1);
      else if (kind === "items") blk.items.splice(n, 1);
      render();
      return;
    }

    var tool = t.getAttribute && t.getAttribute("data-tool");
    if (tool) {
      var idx = blockIndexOf(t);
      if (idx < 0) return;
      syncFromDom();
      if (tool === "up" && idx > 0) { swap(idx, idx - 1); }
      else if (tool === "down" && idx < doc.blocks.length - 1) { swap(idx, idx + 1); }
      else if (tool === "del") { if (confirm("Delete this section?")) { doc.blocks.splice(idx, 1); render(); } }
      else if (tool === "tag") {
        var tag = (prompt("Tag pill (e.g. “new capability”):", "") || "").trim();
        if (tag) { doc.blocks[idx].tag = tag; render(); }
      }
      return;
    }
    var act = t.getAttribute && t.getAttribute("data-act");
    if (act) {
      var bi = blockIndexOf(t);
      if (bi < 0) return;
      syncFromDom();
      var b = doc.blocks[bi];
      if (act === "li-add") b.items.push("");
      else if (act === "abstract-add" || act === "paras-add") b.paras.push("");
      else if (act === "byline-add") b.items.push({ label: "Label", value: "" });
      else if (act === "row-add") b.rows.push(b.head.map(function () { return ""; }));
      else if (act === "col-add") { b.head.push("Column"); b.rows.forEach(function (r) { r.push(""); }); }
      render();
      return;
    }
  });

  // Figure chart selection + height
  page.addEventListener("change", function (e) {
    var t = e.target;
    var idx = blockIndexOf(t);
    if (idx < 0) return;
    if (t.hasAttribute("data-fig-select")) {
      syncFromDom(); doc.blocks[idx].chart = t.value; render();
    } else if (t.hasAttribute("data-fig-height")) {
      syncFromDom(); doc.blocks[idx].height = +t.value || 500; render();
    }
  });

  // What an item currently holds (so an empty one is deleted without a confirm prompt)
  // and what to call it in that prompt.
  function cellText(c) { return (c && typeof c === "object") ? (c.html || "") : String(c == null ? "" : c); }
  function itemText(blk, kind, n) {
    var parts;
    if (kind === "cols") {
      parts = [(blk.head || [])[n]].concat((blk.rows || []).map(function (r) { return cellText(r[n]); }));
    } else if (kind === "rows") {
      parts = ((blk.rows || [])[n] || []).map(cellText);
    } else if (kind === "paras") {
      parts = [(blk.paras || [])[n]];
    } else {
      var it = (blk.items || [])[n];
      parts = (it && typeof it === "object") ? [it.label, it.value] : [it];
    }
    return parts.join("").replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim();
  }
  function itemNoun(blk, kind) {
    if (kind === "cols") return "column";
    if (kind === "rows") return "row";
    if (kind === "paras") return "paragraph";
    return blk.type === "byline" ? "field" : "item";
  }

  function swap(a, b) {
    var tmp = doc.blocks[a]; doc.blocks[a] = doc.blocks[b]; doc.blocks[b] = tmp; render();
  }

  // Drag-to-reorder
  var dragIdx = -1;
  page.addEventListener("dragstart", function (e) {
    var h = e.target;
    if (!h.getAttribute || h.getAttribute("data-tool") !== "drag") { e.preventDefault(); return; }
    dragIdx = blockIndexOf(h);
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", String(dragIdx)); } catch (er) {}
  });
  page.addEventListener("dragover", function (e) {
    if (dragIdx < 0) return;
    e.preventDefault();
    var w = e.target.closest ? e.target.closest(".synth-block") : null;
    page.querySelectorAll(".synth-block.drop-target").forEach(function (x) { x.classList.remove("drop-target"); });
    if (w) w.classList.add("drop-target");
  });
  page.addEventListener("drop", function (e) {
    if (dragIdx < 0) return;
    e.preventDefault();
    var w = e.target.closest ? e.target.closest(".synth-block") : null;
    page.querySelectorAll(".synth-block.drop-target").forEach(function (x) { x.classList.remove("drop-target"); });
    if (w) {
      var to = +w.getAttribute("data-idx");
      syncFromDom();
      var moved = doc.blocks.splice(dragIdx, 1)[0];
      doc.blocks.splice(to, 0, moved);
      render();
    }
    dragIdx = -1;
  });

  // Title: the sidebar field and the in-canvas <h1> are two views of doc.title.
  titleInput.addEventListener("input", function () {
    doc.title = titleInput.value;
    var h1 = page.querySelector("[data-doc-title]");
    if (h1 && document.activeElement !== h1) h1.textContent = doc.title;
    autosave();
  });

  // Sources panel edits
  sourcesList.addEventListener("input", function (e) {
    var t = e.target;
    var field = t.getAttribute("data-src-field");
    if (!field) return;
    var row = t.closest(".synth-source-row");
    var i = +row.getAttribute("data-si");
    doc.sources[i][field] = t.value;
    autosave();
    reRenderReferences();     // keep any References block current
  });
  sourcesList.addEventListener("click", function (e) {
    var row = e.target.closest(".synth-source-row");
    if (!row) return;
    var i = +row.getAttribute("data-si");
    if (e.target.hasAttribute("data-src-del")) {
      if (!confirm("Remove source [" + (i + 1) + "]? Inline citations to it will need updating.")) return;
      doc.sources.splice(i, 1); render();
    } else if (e.target.hasAttribute("data-src-up") && i > 0) {
      var a = doc.sources[i]; doc.sources[i] = doc.sources[i - 1]; doc.sources[i - 1] = a; render();
    } else if (e.target.hasAttribute("data-src-down") && i < doc.sources.length - 1) {
      var b = doc.sources[i]; doc.sources[i] = doc.sources[i + 1]; doc.sources[i + 1] = b; render();
    }
  });
  document.getElementById("synth-add-source").addEventListener("click", function () {
    doc.sources.push({ authors: "", title: "", journal: "", year: "", url: "", doi: "" });
    render();
  });
  function reRenderReferences() {
    // Re-render only References blocks in place without disturbing the caret elsewhere.
    doc.blocks.forEach(function (b, idx) {
      if (b.type !== "references") return;
      var w = page.querySelector('.synth-block[data-idx="' + idx + '"]');
      if (w) w.innerHTML = blockInner(b, idx) + blockTools();
    });
  }


  // ========================================================================
  //  Inline formatting toolbar (bold / italic / tag / cite)
  // ========================================================================
  function currentEditable() {
    var sel = window.getSelection();
    if (!sel.rangeCount) return null;
    var node = sel.anchorNode;
    if (node && node.nodeType === 3) node = node.parentElement;
    if (!node || !node.closest) return null;
    var host = node.closest('[contenteditable="true"]');
    if (host && page.contains(host)) return host;
    return null;
  }
  function updateInlineBar() {
    var sel = window.getSelection();
    var host = currentEditable();
    if (!host || sel.isCollapsed || !sel.rangeCount) { inlineBar.hidden = true; return; }
    var rect = sel.getRangeAt(0).getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) { inlineBar.hidden = true; return; }
    inlineBar.hidden = false;
    var bw = inlineBar.offsetWidth || 160;
    var left = Math.max(8, rect.left + rect.width / 2 - bw / 2);
    var top = rect.top - inlineBar.offsetHeight - 8;
    if (top < 8) top = rect.bottom + 8;
    inlineBar.style.left = left + "px";
    inlineBar.style.top = top + "px";
  }
  document.addEventListener("selectionchange", updateInlineBar);
  window.addEventListener("scroll", function () { if (!inlineBar.hidden) updateInlineBar(); }, true);

  inlineBar.addEventListener("mousedown", function (e) { e.preventDefault(); }); // keep selection
  inlineBar.addEventListener("click", function (e) {
    var cmd = e.target.getAttribute("data-cmd") || (e.target.parentElement && e.target.parentElement.getAttribute("data-cmd"));
    if (!cmd) return;
    var host = currentEditable();
    if (!host) return;
    if (cmd === "bold") document.execCommand("bold");
    else if (cmd === "italic") document.execCommand("italic");
    else if (cmd === "clear") document.execCommand("removeFormat");
    else if (cmd === "tag") {
      var text = String(window.getSelection());
      if (text) document.execCommand("insertHTML", false, '<span class="tag">' + escText(text) + '</span>');
    } else if (cmd === "cite") { openCite(host); return; }
    // sync model after formatting
    var idx = blockIndexOf(host);
    var field = host.getAttribute("data-field");
    if (idx >= 0 && field != null) setField(doc.blocks[idx], field, cleanInline(host.innerHTML));
    autosave();
  });

  // Cite popover
  var popover = null;
  function closePopover() {
    if (popover) { popover.remove(); popover = null; }
    page.querySelectorAll(".synth-gap.open").forEach(function (g) { g.classList.remove("open"); });
  }
  document.addEventListener("mousedown", function (e) {
    if (popover && !popover.contains(e.target) && !inlineBar.contains(e.target)) closePopover();
  });
  function openCite(host) {
    closePopover();
    var savedRange = window.getSelection().rangeCount ? window.getSelection().getRangeAt(0).cloneRange() : null;
    popover = document.createElement("div");
    popover.className = "synth-popover";
    if (!doc.sources.length) {
      popover.innerHTML = '<div style="padding:6px 8px;color:#8a94a3">No sources yet — add one in the Sources panel first.</div>';
    } else {
      popover.innerHTML = doc.sources.map(function (s, i) {
        var label = s.authors || s.title || ("Source " + (i + 1));
        return '<div class="synth-pop-item" data-cite="' + (i + 1) + '"><b>[' + (i + 1) + ']</b> '
          + escText(label) + (s.year ? " (" + escText(s.year) + ")" : "") + '</div>';
      }).join("");
    }
    document.body.appendChild(popover);
    var r = inlineBar.getBoundingClientRect();
    popover.style.left = r.left + "px";
    popover.style.top = (r.bottom + 6) + "px";
    popover.addEventListener("click", function (e) {
      var n = e.target.closest ? e.target.closest("[data-cite]") : null;
      if (!n) return;
      var k = n.getAttribute("data-cite");
      var sel = window.getSelection();
      sel.removeAllRanges();
      if (savedRange) sel.addRange(savedRange);
      host.focus();
      document.execCommand("insertHTML", false,
        '<sup class="r"><a href="#r' + k + '">' + k + '</a></sup>');
      var idx = blockIndexOf(host);
      var field = host.getAttribute("data-field");
      if (idx >= 0 && field != null) setField(doc.blocks[idx], field, cleanInline(host.innerHTML));
      closePopover();
      inlineBar.hidden = true;
      autosave();
    });
  }

  // ========================================================================
  //  Load / Save / Build
  // ========================================================================
  function fetchJSON(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }
  function post(url, body) {
    return fetchJSON(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": CSRF },
      credentials: "same-origin",
      body: JSON.stringify(body)
    });
  }

  function refreshPaperList(selected) {
    fetchJSON(PAPERS_URL, { credentials: "same-origin" }).then(function (j) {
      var papers = j.papers || [];
      openSel.innerHTML = '<option value="">Open a paper…</option>'
        + papers.map(function (p) {
          return '<option value="' + escAttr(p.name) + '"' + (p.name === selected ? " selected" : "") + '>'
            + escText(p.name) + '</option>';
        }).join("");
    }).catch(function () {});
  }

  function openPaper(name, note) {
    setStatus("Opening…");
    return fetchJSON(nameTmpl(LOAD_TMPL, name), { credentials: "same-origin" }).then(function (j) {
      doc = normalize(j.doc || starterDoc());
      currentName = j.name;
      render();
      openSel.value = j.name;
      autosave();
      setStatus(note || "Opened “" + j.name + "”.", "ok");
    }).catch(function (err) { setStatus("Open failed: " + err.message, "err"); });
  }

  openSel.addEventListener("change", function () {
    if (openSel.value) openPaper(openSel.value);
  });

  document.getElementById("synth-new").addEventListener("click", function () {
    if (!confirm("Start a new blank paper? Unsaved changes to the current one will be lost.")) return;
    doc = starterDoc(); currentName = null; render(); openSel.value = "";
    autosave();
    setStatus("New paper.", "ok");
  });

  document.getElementById("synth-save").addEventListener("click", function () {
    syncFromDom();
    var name = docName();
    setStatus("Saving…");
    post(SAVE_URL, { name: name, doc: doc, description: "" }).then(function (j) {
      currentName = j.name;
      autosave();
      setStatus("Saved “" + j.name + "”.", "ok");
      refreshPaperList(j.name);
    }).catch(function (err) { setStatus("Save failed: " + err.message, "err"); });
  });

  document.getElementById("synth-build").addEventListener("click", function () {
    syncFromDom();
    var name = docName();
    setStatus("Building… embedding live charts.");
    post(BUILD_URL, { doc: doc, output_name: name, name: name }).then(function (j) {
      setStatus("Built “" + j.name + "” → open it from the Dashboard's Visualizations.", "ok");
    }).catch(function (err) { setStatus("Build failed: " + err.message, "err"); });
  });

  function slug(s) {
    return String(s || "").trim().replace(/[^\w.\-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80);
  }

  // Normalise a loaded doc: table cells -> {html,cls}, ensure arrays exist.
  function normalize(d) {
    d = d || {};
    d.title = d.title || "Untitled paper";
    d.blocks = d.blocks || [];
    d.sources = d.sources || [];
    d.blocks.forEach(function (b) {
      if (b.type === "callout" && !b.paras) {
        // A callout's body is a list of paragraphs; lift a legacy single `html` body
        // into it (the builder accepts either, the editor only edits `paras`).
        b.paras = b.html ? [b.html] : [""];
        delete b.html;
      }
      if (b.type === "table") {
        b.head = b.head || [];
        b.rows = (b.rows || []).map(function (row) {
          return row.map(function (c) {
            return (c && typeof c === "object") ? { html: c.html || "", cls: c.cls || "" } : { html: escText(c), cls: "" };
          });
        });
      }
    });
    return d;
  }

  // ========================================================================
  //  Assistant bridge — the agent edits papers server-side (via the same
  //  paper_ops the editor's own Save uses), so after a turn that touched one we
  //  reopen it from disk and the user sees the change land in the canvas.
  // ========================================================================
  window.Synthesize = {
    openName: function () { return currentName; },
    refresh: function () {
      refreshPaperList(currentName);
      if (!currentName) return Promise.resolve(false);
      return openPaper(currentName, "Updated by the assistant.").then(function () { return true; });
    }
  };

  // ========================================================================
  //  Init
  // ========================================================================
  (function init() {
    // A server-injected initial doc (e.g. "open this paper on load") wins over the
    // autosaved draft; otherwise restore the local draft (doc *and* the filename it
    // is bound to), otherwise start fresh.
    var initial = readJSON("synthesize-initial", null);
    var draft = initial ? null : readDraft();
    if (initial && initial.blocks) {
      doc = normalize(initial);
      currentName = initial.name || null;
    } else if (draft) {
      doc = normalize(draft.doc);
      currentName = draft.name;
    } else {
      doc = normalize(starterDoc());
    }
    render();
    refreshPaperList(currentName);
  })();
})();
