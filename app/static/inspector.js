/* VITalWatch — worklist + inspector (Phase 4, prompt.md §7.2).
   ---------------------------------------------------------------------------
   Progressive enhancement over a server-rendered queue. With JavaScript
   disabled, every row's primary link opens the full record page and nothing
   here is missed. With it, a row opens in a side inspector without losing the
   queue, its filters, or the reader's scroll position.

   The contract, kept here rather than asserted in copy:
   · The inspector is never the only path — the full record page (/ae/{id})
     is a real, shareable URL, and ?inspect=<id> deep-links the open state.
   · Focus moves into the panel on open; Escape closes it and returns focus
     to the row that triggered it. Arrow keys walk the queue.
   · Stale fetches are discarded: a slow earlier response never overwrites a
     newer selection.
   · Loading, error, and permission (403) states are distinct — a failed load
     never reads as an empty record, and "cannot see this" is never "nothing
     here" (§10.1).
   · Below 640px the panel is a full page (queue.css); this script does not
     need to know — the same markup serves both. */
(function () {
  "use strict";

  var root = document.querySelector("[data-inspector]");
  var list = document.querySelector("[data-inspectable]");
  if (!root || !list) { return; }

  var panel = root.querySelector("[data-inspector-panel]");
  var body = root.querySelector("[data-inspector-body]");
  var closeButtons = root.querySelectorAll("[data-inspector-close]");

  var lastTrigger = null;   // the row link that opened the panel — focus returns here
  var currentId = null;     // data-inspect-id of the open record
  var requestSeq = 0;       // stale-response guard

  var LOADING_HTML =
    '<div class="state state-loading" role="status">' +
    '<p class="state-title">Loading…</p>' +
    '<p class="state-body">The queue stays where it is while the record loads.</p></div>';

  function rows() {
    return Array.prototype.slice.call(list.querySelectorAll(".q-row[data-inspect-url]"));
  }

  function markSelected(id) {
    rows().forEach(function (row) {
      row.classList.toggle("q-row-selected", row.getAttribute("data-inspect-id") === id);
    });
  }

  function setInspectParam(id) {
    var url = new URL(window.location.href);
    if (id) { url.searchParams.set("inspect", id); } else { url.searchParams.delete("inspect"); }
    return url;
  }

  function pushState(id) {
    window.history.pushState({ inspect: id || null }, "", setInspectParam(id));
  }

  function errorHtml(status, recordUrl) {
    var title, detail;
    if (status === 403) {
      title = "Not authorized";
      detail = "Your role may not review this record. The queue shows only what your " +
               "permissions cover; this record is outside them.";
    } else if (status === 404) {
      title = "Record not found";
      detail = "This record no longer exists at this address. The queue may be stale — " +
               "reload it to see the current set.";
    } else {
      title = "The record failed to load";
      detail = "Whether anything changed is unknown — nothing was written by this view. " +
               "Check your connection and try again.";
    }
    return '<div class="state ' + (status === 403 ? "state-permission" : "state-error") + '" role="alert">' +
      "<p class=\"state-title\">" + title + "</p>" +
      "<p class=\"state-body\">" + detail + "</p>" +
      (recordUrl ? '<a class="btn btn-secondary" href="' + recordUrl + '">Open the full record page</a>' : "") +
      "</div>";
  }

  function openRow(row, push) {
    if (!row) { return; }
    var url = row.getAttribute("data-inspect-url");
    var recordUrl = row.getAttribute("data-record-url") || url;
    currentId = row.getAttribute("data-inspect-id");
    lastTrigger = row.querySelector(".q-row-id") || row;

    var seq = ++requestSeq;
    root.hidden = false;
    // Two frames so the transition actually runs from translateX(102%).
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { root.classList.add("is-open"); });
    });
    body.innerHTML = LOADING_HTML;
    markSelected(currentId);
    if (push) { pushState(currentId); }

    window.fetch(url, { headers: { "X-Requested-With": "inspector" }, credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) { var err = new Error(res.statusText); err.status = res.status; throw err; }
        return res.text();
      })
      .then(function (html) {
        if (seq !== requestSeq) { return; }  // a newer selection already landed
        body.innerHTML = html;
        var close = body.querySelector("[data-inspector-close]") ||
                    root.querySelector(".inspector-close");
        if (close) { close.focus({ preventScroll: true }); }
      })
      .catch(function (err) {
        if (seq !== requestSeq) { return; }
        body.innerHTML = errorHtml(err.status || 0, recordUrl);
      });
  }

  function closeInspector(restoreFocus) {
    if (root.hidden) { return; }
    requestSeq += 1;  // cancel any in-flight render
    root.classList.remove("is-open");
    currentId = null;
    markSelected(null);
    window.setTimeout(function () { root.hidden = true; }, 220);
    if (window.location.search.indexOf("inspect=") !== -1) { pushState(null); }
    if (restoreFocus !== false && lastTrigger && document.contains(lastTrigger)) {
      lastTrigger.focus({ preventScroll: true });
    }
  }

  /* Row selection: a click anywhere on the row opens the inspector — except
     on real controls inside it, which keep their own meaning. The primary
     link is intercepted too; without JS it would have navigated to the full
     record page, which is the no-JS fallback doing its job. */
  list.addEventListener("click", function (ev) {
    var row = ev.target.closest(".q-row[data-inspect-url]");
    if (!row) { return; }
    var control = ev.target.closest("a, button, select, input, textarea, label, details, summary, form");
    if (control && !control.classList.contains("q-row-id")) { return; }
    ev.preventDefault();
    openRow(row, true);
  });

  /* Keyboard: arrows walk the queue's primary links; Enter on a link opens
     the inspector through the same intercepted click as the pointer. */
  list.addEventListener("keydown", function (ev) {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") { return; }
    var links = rows().map(function (row) { return row.querySelector(".q-row-id"); }).filter(Boolean);
    var at = links.indexOf(document.activeElement);
    if (at === -1) { return; }
    ev.preventDefault();
    var next = ev.key === "ArrowDown" ? Math.min(at + 1, links.length - 1) : Math.max(at - 1, 0);
    links[next].focus();
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !root.hidden) {
      ev.preventDefault();
      closeInspector(true);
    }
  });

  Array.prototype.forEach.call(closeButtons, function (btn) {
    btn.addEventListener("click", function () { closeInspector(true); });
  });

  /* Back/forward: the URL is the state, so browser navigation reopens or
     closes the panel exactly as a pasted link would. */
  window.addEventListener("popstate", function () {
    var id = new URL(window.location.href).searchParams.get("inspect");
    if (!id) { closeInspector(false); return; }
    var row = list.querySelector('.q-row[data-inspect-id="' + CSS.escape(id) + '"]');
    if (row) { openRow(row, false); } else { closeInspector(false); }
  });

  /* Deep link: ?inspect=<id> reopens the same state on arrival. If the row is
     on another page of the queue, the record page is the honest destination —
     redirect there rather than pretending the panel can show what the list
     does not. */
  (function boot() {
    var id = new URL(window.location.href).searchParams.get("inspect");
    if (!id) { return; }
    var row = list.querySelector('.q-row[data-inspect-id="' + CSS.escape(id) + '"]');
    if (row) {
      openRow(row, false);
    } else {
      var recordUrl = list.getAttribute("data-record-base");
      if (recordUrl) { window.location.replace(recordUrl + encodeURIComponent(id)); }
    }
  })();
})();
