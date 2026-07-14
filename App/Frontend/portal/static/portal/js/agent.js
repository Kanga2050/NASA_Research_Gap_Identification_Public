/* The assistant dock — a chat panel that floats above all three tabs.
 *
 * It is not part of any tab, because the agent works on all of them: it can read the
 * user's data and queue pipeline steps (Dashboard), read/author/run node pipelines
 * (Studio), and read, patch and build the paper that is open (Synthesize).
 *
 * Two pieces of wiring make it feel "live" rather than like a chatbot in a corner:
 *   1. every message carries CONTEXT — which tab is showing, which paper is open —
 *      so "add a conclusion to this paper" resolves to the right document;
 *   2. the reply carries back the TOOLS the agent called, so whatever it changed is
 *      reloaded in place (the open paper is reopened from disk, the Studio's pipeline
 *      list refreshed) instead of the user having to reload the page.
 */
(function () {
  "use strict";
  var dock = document.getElementById("agent-dock");
  var fab = document.getElementById("agent-fab");
  if (!dock || !fab) return;

  var CSRF = dock.getAttribute("data-csrf");
  var CHAT_URL = dock.getAttribute("data-chat-url");
  var RESET_URL = dock.getAttribute("data-reset-url");
  var OPEN_KEY = "agent:open";

  var form = document.getElementById("agent-form");
  var input = document.getElementById("agent-input");
  var sendBtn = document.getElementById("agent-send");
  var log = document.getElementById("agent-log");
  var empty = document.getElementById("agent-empty");
  var contextEl = document.getElementById("agent-context");

  // ---- open / close -------------------------------------------------------
  function setOpen(open) {
    dock.hidden = !open;
    fab.setAttribute("aria-expanded", open ? "true" : "false");
    fab.classList.toggle("hidden", open);
    try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (e) {}
    if (open) { showContext(); scrollToBottom(); if (!input.disabled) input.focus(); }
  }
  fab.addEventListener("click", function () { setOpen(true); });
  document.getElementById("agent-close").addEventListener("click", function () { setOpen(false); });
  var wasOpen = false;
  try { wasOpen = localStorage.getItem(OPEN_KEY) === "1"; } catch (e) {}
  if (wasOpen) setOpen(true);

  // ---- context: what the user is looking at -------------------------------
  function activeTab() {
    var el = document.querySelector(".tab.active[data-tab]");
    return el ? el.getAttribute("data-tab") : "dashboard";
  }
  function openPaper() {
    return (window.Synthesize && window.Synthesize.openName()) || "";
  }
  function showContext() {
    var tab = activeTab();
    var paper = openPaper();
    var label = "Working on the " + tab + " tab";
    if (tab === "synthesize" && paper) label += " · paper “" + paper + "”";
    contextEl.textContent = label;
  }
  // The tab bar swaps panels without a reload, so keep the context line current.
  document.querySelectorAll(".tab[data-tab]").forEach(function (t) {
    t.addEventListener("click", function () { setTimeout(showContext, 0); });
  });
  showContext();

  // ---- chat ---------------------------------------------------------------
  function scrollToBottom() { log.scrollTop = log.scrollHeight; }

  function addMessage(role, text) {
    if (empty) empty.style.display = "none";
    var el = document.createElement("div");
    el.className = "agent-msg " + role;
    el.textContent = text;
    log.appendChild(el);
    scrollToBottom();
    return el;
  }
  function setBusy(busy) {
    input.disabled = busy;
    sendBtn.disabled = busy;
  }

  // Reload whatever the agent's tools just changed, so the edit lands in front of
  // the user rather than waiting for a refresh.
  var PAPER_TOOLS = { save_paper: 1, edit_paper: 1, build_paper: 1 };
  var STUDIO_TOOLS = { save_studio_pipeline: 1 };
  function applyChanges(tools) {
    if (!tools || !tools.length) return;
    var touchedPaper = tools.some(function (t) { return PAPER_TOOLS[t]; });
    var touchedStudio = tools.some(function (t) { return STUDIO_TOOLS[t]; });
    if (touchedPaper && window.Synthesize) {
      window.Synthesize.refresh().then(showContext);
    }
    if (touchedStudio && window.Studio) window.Studio.refreshTemplates();
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;

    addMessage("user", text);
    input.value = "";
    setBusy(true);
    var pending = addMessage("assistant pending", "Thinking…");

    var body = "message=" + encodeURIComponent(text)
      + "&tab=" + encodeURIComponent(activeTab())
      + "&paper=" + encodeURIComponent(openPaper());

    fetch(CHAT_URL, {
      method: "POST",
      headers: { "X-CSRFToken": CSRF, "Content-Type": "application/x-www-form-urlencoded" },
      credentials: "same-origin",
      body: body,
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        pending.classList.remove("pending");
        if (res.ok && res.data.reply) {
          pending.textContent = res.data.reply;
          applyChanges(res.data.tools);
        } else {
          pending.classList.add("error-msg");
          pending.textContent = res.data.error || "The assistant could not respond.";
        }
        scrollToBottom();
      })
      .catch(function () {
        pending.classList.remove("pending");
        pending.classList.add("error-msg");
        pending.textContent = "Network error. Please try again.";
      })
      .finally(function () {
        setBusy(false);
        input.focus();
      });
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  document.getElementById("agent-reset").addEventListener("click", function () {
    fetch(RESET_URL, { method: "POST", headers: { "X-CSRFToken": CSRF }, credentials: "same-origin" })
      .then(function () {
        log.querySelectorAll(".agent-msg").forEach(function (n) { n.remove(); });
        if (empty) empty.style.display = "";
      });
  });
})();
