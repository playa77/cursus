/* Cursus WP-16 visual reference — minimal vanilla JS.
   Preview-only behavior: no orchestrator is contacted; all data is synthetic. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* Phase/attempt variant switching via sidebar links; preview-state pills via sidebar controls */
  var groupToggle = document.getElementById("nav-preview-toggle");
  if (groupToggle) groupToggle.addEventListener("click", function () {
    var expanded = groupToggle.getAttribute("aria-expanded") === "true";
    groupToggle.setAttribute("aria-expanded", String(!expanded));
    var group = document.getElementById("nav-preview-group");
    if (group) group.hidden = expanded;
  });

  /* ---------------- Theme behavior: dark default / light default / follow OS ---------------- */
  var behaviorRadios = $$('input[name="theme-behavior"]');
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function applyBehavior(v) {
    if (v === "dark" || v === "light") {
      document.documentElement.setAttribute("data-theme", v);
      document.documentElement.setAttribute("data-behavior", v);
    } else {
      /* follow OS until overridden */
      document.documentElement.setAttribute("data-theme", media.matches ? "dark" : "light");
      document.documentElement.setAttribute("data-behavior", "system");
    }
  }
  behaviorRadios.forEach(function (r) {
    r.addEventListener("change", function () { if (r.checked) applyBehavior(r.value); });
  });
  media.addEventListener("change", function () {
    if (document.documentElement.getAttribute("data-behavior") === "system") applyBehavior("system");
  });
  applyBehavior("system");

  /* ---------------- Router (hash routes mirror server routes) ---------------- */
  var routes = {
    "overview": { view: "view-overview", title: "Overview", nav: "overview" },
    "attempts": { view: "view-attempts", title: "Attempts", nav: "attempts" },
    "intake":   { view: "view-intake",   title: "New run & intake", nav: "intake" },
    "phase-auth":  { view: "view-phase", title: "auth-refactor", phase: "auth", nav: "phase-auth" },
    "phase-pr":    { view: "view-phase", title: "fix-sse-flap", phase: "pr", nav: "phase-pr" },
    "phase-files": { view: "view-phase", title: "launch-brief", phase: "files", nav: "phase-files" },
    "attempt-run":    { view: "view-attempt", title: "att-9f2c41d0", attempt: "run" },
    "attempt-disc":   { view: "view-attempt", title: "att-8d41b2e7", attempt: "disc" },
    "attempt-parked": { view: "view-attempt", title: "att-5e93c8aa", attempt: "parked" },
    /* alias keys so in-content links with entity hashes resolve to the same views */
    "phase/auth-refactor": { view: "view-phase", title: "auth-refactor", phase: "auth", nav: "phase-auth" },
    "phase/fix-sse-flap":  { view: "view-phase", title: "fix-sse-flap", phase: "pr", nav: "phase-pr" },
    "phase/launch-brief":  { view: "view-phase", title: "launch-brief", phase: "files", nav: "phase-files" },
    "attempt/att-9f2c41d0": { view: "view-attempt", title: "att-9f2c41d0", attempt: "run" },
    "attempt/att-8d41b2e7": { view: "view-attempt", title: "att-8d41b2e7", attempt: "disc" },
    "attempt/att-5e93c8aa": { view: "view-attempt", title: "att-5e93c8aa", attempt: "parked" }
  };

  function routeKey() {
    var h = (location.hash || "#/overview").replace(/^#\//, "");
    return routes[h] ? h : "overview";
  }

  function render() {
    var key = routeKey();
    var r = routes[key];
    $$(".view").forEach(function (v) { v.hidden = true; });
    var el = document.getElementById(r.view);
    if (el) el.hidden = false;
    document.getElementById("view-title").textContent = r.title;
    document.title = "Cursus — " + r.title + " (WP-16 visual reference)";
    $$(".nav__item").forEach(function (a) {
      a.classList.toggle("is-active", a.getAttribute("data-route") === (r.nav || key));
    });
    var prevStates = document.getElementById("ov-preview-states");
    if (prevStates) prevStates.hidden = key !== "overview";
    if (r.phase) setPhaseVariant(r.phase);
    if (r.attempt) setAttemptVariant(r.attempt);
    if (r.attempt) {
      var meta = {
        "run":    { id: "att-9f2c41d0", pkg: "package WP-14", step: "step produce", ref: "wp/m3/auth-refactor/WP-14/att-9f2c41d0/candidate" },
        "disc":   { id: "att-8d41b2e7", pkg: "package WP-13", step: "step verify",  ref: "verifying candidate 4d1e… (runner snapshot)" },
        "parked": { id: "att-5e93c8aa", pkg: "package WP-12", step: "step produce", ref: "wp/m3/auth-refactor/WP-12/att-5e93c8aa/candidate" }
      }[r.attempt];
      var pkgEl = document.getElementById("atthead-pkg");
      if (pkgEl) pkgEl.textContent = meta.pkg;
      var stepEl = document.getElementById("atthead-step");
      if (stepEl) stepEl.textContent = meta.step;
      var refEl = document.getElementById("atthead-ref");
      if (refEl) refEl.textContent = meta.ref;
    }
    window.scrollTo(0, 0);
  }

  /* Attempt links in tables point to variant routes */
  $$('a[href="#/attempt/att-9f2c41d0"]').forEach(function (a) { a.href = "#/attempt-run"; });
  $$('a[href="#/attempt/att-8d41b2e7"]').forEach(function (a) { a.href = "#/attempt-disc"; });
  $$('a[href="#/attempt/att-5e93c8aa"]').forEach(function (a) { a.href = "#/attempt-parked"; });

  window.addEventListener("hashchange", render);
  if (!location.hash) location.hash = "#/overview";
  render();

  /* ---------------- Overview state switcher ---------------- */
  var ovState = "loaded";
  var ovBody = $(".ov-body");
  function setOvState(s) {
    ovState = s;
    ovBody.classList.toggle("ovstate-empty", s === "empty");
    $$("[data-ovstate]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-ovstate") === s));
    });
    $("#ov-reconnect").hidden = s !== "reconnecting";
    $("#ov-error").hidden = s !== "error";
    $$("[data-show-when]", ovBody).forEach(function (el) {
      var when = (el.getAttribute("data-show-when") || "").split(",");
      var show = when.indexOf(s) !== -1;
      el.hidden = !show;
    });
  }
  $$("[data-ovstate]").forEach(function (b) {
    b.addEventListener("click", function () { setOvState(b.getAttribute("data-ovstate")); });
  });
  setOvState("loaded");

  /* ---------------- Phase variant switcher ---------------- */
  function setPhaseVariant(v) {
    $$("[data-phase-variant]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-phase-variant") === v));
    });
    $$("[data-phase-block]").forEach(function (el) { el.hidden = el.getAttribute("data-phase-block") !== v; });
  }
  $$("[data-phase-variant]").forEach(function (b) {
    b.addEventListener("click", function () { setPhaseVariant(b.getAttribute("data-phase-variant")); });
  });

  /* ---------------- Attempt variant switcher ---------------- */
  function setAttemptVariant(v) {
    $$("[data-attempt-variant]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-attempt-variant") === v));
    });
    $$("[data-attempt-block]").forEach(function (el) { el.hidden = el.getAttribute("data-attempt-block") !== v; });
  }
  $$("[data-attempt-variant]").forEach(function (b) {
    b.addEventListener("click", function () { setAttemptVariant(b.getAttribute("data-attempt-variant")); });
  });

  /* ---------------- Demo log stream (SSE stand-in) ---------------- */
  var log = $("#log-stream");
  var LINES = [
    { kind: "log", text: "pi: turn 3 — reading src/auth/session.py (allowed tool: read)" },
    { kind: "log", text: "pi: applying edit to src/auth/session.py — replace manual expiry checks with store helper" },
    { kind: "log", text: "pi: running pytest tests/auth -x (scoped verifier command)" },
    { kind: "log", text: "runner: spool seq 118 → acknowledged through 118" },
    { kind: "usage", text: "usage in 1,214,332 / out 418,905 tok · cost $0.84 (reported)" },
    { kind: "log", text: "pi: completion report drafted — summary: token-store migration path completed for WP-14; suggested files: src/auth/session.py, tests/auth/test_session.py" },
    { kind: "checkpoint", text: "debug checkpoint — candidate 4d1e… pinned on refs/heads/wp/m3/auth-refactor/WP-14/att-9f2c41d0/candidate (very long line to prove wrapping: refs/heads/wp/m3/auth-refactor/WP-14/att-9f2c41d0/candidate/4d1e2b7c9f0a1d3e5f60718293a4b5c6d7e8f9012)" },
    { kind: "command_result", text: "steer cmd-77 → accepted (acceptance is not model consumption)" },
    { kind: "log", text: "pi: turn 3 continuation — integrating reviewer note about clock skew in expiry math" },
    { kind: "log", text: "runner: heartbeat ok · slots pi 2/2 · spool 0 B" }
  ];
  var logPaused = false, logTimer = null, li = 0;
  function userAtBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  }
  function pushLine(entry) {
    var stick = userAtBottom();
    var row = document.createElement("div");
    row.className = "logline logline--kind-" + entry.kind;
    var t = document.createElement("time");
    t.textContent = new Date().toTimeString().slice(0, 8);
    var msg = document.createElement("span");
    msg.className = "log__msg";
    msg.textContent = entry.text; /* textContent only — payloads are data, never markup */
    row.appendChild(t); row.appendChild(msg);
    log.appendChild(row);
    while (log.children.length > 220) log.removeChild(log.firstChild);
    if (stick && !logPaused) log.scrollTop = log.scrollHeight;
  }
  function tick() { pushLine(LINES[li % LINES.length]); li++; }
  if (log) {
    LINES.slice(0, 5).forEach(pushLine); li = 5;
    logTimer = setInterval(tick, 1100);
    var pauseBtn = $("[data-log-pause]");
    pauseBtn.addEventListener("click", function () {
      logPaused = !logPaused;
      pauseBtn.setAttribute("aria-pressed", String(logPaused));
      pauseBtn.textContent = logPaused ? "Resume autoscroll" : "Pause autoscroll";
    });
    log.addEventListener("scroll", function () {
      if (!userAtBottom() && !logPaused) {
        logPaused = true;
        pauseBtn.setAttribute("aria-pressed", "true");
        pauseBtn.textContent = "Resume autoscroll";
      }
    });
    $("[data-log-copy]").addEventListener("click", function () {
      var text = Array.prototype.map.call(log.children, function (c) { return c.textContent; }).join("\n");
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text);
    });
  }

  /* ---------------- Confirmation dialog ---------------- */
  var dialog = $("#confirm-dialog");
  function confirmDialog(title, body, actionLabel) {
    return new Promise(function (resolve) {
      $("#confirm-title").textContent = title;
      $("#confirm-body").textContent = body;
      $("#confirm-action").textContent = actionLabel;
      dialog.addEventListener("close", function onClose() {
        dialog.removeEventListener("close", onClose);
        resolve(dialog.returnValue === "confirm");
      });
      dialog.showModal();
    });
  }

  /* ---------------- Demo interactions ---------------- */

  /* Interview answer: recorded once */
  $$("[data-demo-answer]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ta = form.querySelector("textarea");
      if (!ta.value.trim()) { ta.focus(); return; }
      form.classList.add("is-done");
      var done = form.parentElement.querySelector(".q__done");
      if (done) done.hidden = false;
      else {
        done = document.createElement("p");
        done.className = "q__done";
        done.innerHTML = '<span class="chip chip--ok">recorded</span> Answer recorded against the current spec revision.';
        form.parentElement.appendChild(done);
      }
    });
  });

  /* Steer: pending → accepted */
  $$("[data-demo-steer]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ta = form.querySelector("textarea");
      if (!ta.value.trim()) { ta.focus(); return; }
      var state = form.querySelector(".steer__state");
      ta.value = "";
      state.innerHTML = '<span class="chip chip--warn">steer: pending</span> request submitted — awaiting runner disposition';
      setTimeout(function () {
        state.innerHTML = '<span class="chip chip--ok">steer: accepted</span> disposition committed';
      }, 1400);
    });
  });

  /* Cancel phase (danger, confirmed) */
  var cancelBtn = $("[data-demo-cancel]");
  if (cancelBtn) cancelBtn.addEventListener("click", function () {
    confirmDialog("Cancel phase auth-refactor?",
      "This locks the phase, cancels unclaimed work and queues stop for active attempts. Cancellation is reported final only after live attempts are proven stopped and publication intents are reconciled.",
      "Cancel phase")
      .then(function (ok) {
        if (!ok) return;
        $("#ph-cancel-banner").hidden = false;
        cancelBtn.disabled = true;
        cancelBtn.textContent = "Cancellation requested";
      });
  });

  /* Abandon (parked-unknown only, reason required) */
  var abandonForm = $("[data-demo-abandon]");
  if (abandonForm) {
    var reason = $("#abandon-reason");
    var submit = $("[data-abandon-submit]");
    reason.addEventListener("input", function () {
      submit.disabled = !reason.value.trim();
    });
    abandonForm.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!reason.value.trim()) { reason.focus(); return; }
      confirmDialog("Abandon attempt att-5e93c8aa?",
        "Exceptional action. Abandonment records the decision, invalidates this attempt’s ability to advance the phase, and releases its claim. A late result cannot change the replacement’s state. Reason: “" + reason.value.trim() + "”",
        "Abandon attempt")
        .then(function (ok) {
          if (!ok) return;
          abandonForm.querySelector(".q__actions").hidden = true;
          $("#abandon-done").hidden = false;
        });
    });
  }

  /* Declare unrecoverable (disconnected variant) */
  var unrecBtn = $("[data-demo-unrecoverable]");
  if (unrecBtn) unrecBtn.addEventListener("click", function () {
    confirmDialog("Declare att-8d41b2e7 unrecoverable?",
      "This records your evidence of permanent loss or a missing record for this unavailable attempt. A disconnected runner alone is not such evidence — confirm you have positive proof.",
      "Declare unrecoverable")
      .then(function (ok) {
        if (!ok) return;
        unrecBtn.disabled = true;
        unrecBtn.textContent = "Declared unrecoverable — recorded";
      });
  });

  /* Demo downloads (local blob — no network) */
  $$("[data-demo-download]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var name = btn.getAttribute("data-demo-download");
      var body = "Cursus synthetic artifact — " + name + "\n" +
        "sha256 (demo): 9f2c…e41\n" +
        "In the deployed product this file is served by GET /artifacts/{id} " +
        "as an attachment with X-Cursus-Sha256 and X-Cursus-File-Name headers.\n";
      var blob = new Blob([body], { type: "text/plain" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    });
  });

  /* Intake submit (synthetic Reply) */
  $$("[data-intake-submit]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var state = form.querySelector(".intake-state");
      state.innerHTML = '<span class="chip chip--ok">phase created</span> ph-8c31d2a4 · queued: resolve_input → interview/plan · cursor 8,424 (synthetic Reply)';
    });
  });

  /* Phase filter (overview table) */
  var filter = $("#phase-filter");
  if (filter) filter.addEventListener("input", function () {
    var q = filter.value.toLowerCase();
    $$('[data-filterable] tbody tr').forEach(function (tr) {
      if (tr.classList.contains("empty-demo")) return;
      tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) === -1;
    });
  });
})();
