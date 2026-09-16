/* VITalWatch — live coding assist (prompt.md §7.3).
   ---------------------------------------------------------------------------
   The one mandatory security fix of the redesign, as a behavior contract:

   · The narrative travels ONLY in a JSON request body (POST /api/pv/code),
     never in a URL query string — the deprecated GET route stays deprecated.
   · The CSRF token goes in the X-CSRF-Token header, read from the page's own
     <meta name="csrf-token">; the cookie itself stays HttpOnly.
   · The suggestion is advisory. Where a review form ships final-term/final-code
     fields ([data-coding-final-term]/[data-coding-final-code]), choosing a
     suggestion only PRE-FILLS them — the audited decision is still the human's
     submit. Where they do not exist (staff intake), the assist is read-only.
   · Every suggestion shows its match basis (exact / phrase / fuzzy) so a 0.81
     fuzzy hit is never mistaken for an exact one (app/pv.py makes the same
     distinction; this file only renders it).
   · Stale responses are discarded: a slower earlier request may never
     overwrite a newer one (AbortController + a monotonic request id).

   Markup contract (server-rendered, this script only hydrates):

     <textarea|input data-coding-source>          narrative to match
     <div class="assist" data-coding-assist       mount point
          [data-coding-autoload]                  run once on load (review form)
          hidden aria-live="polite"></div>

   Both attributes live inside the same <form> (or common ancestor); the script
   resolves the source by walking up from the mount. Self-gating: with no mount
   on the page it does nothing and binds nothing. */

(function () {
  "use strict";

  var DEBOUNCE_MS = 450;   /* a reader's pause, not a per-keystroke storm */
  var MIN_LEN = 3;

  var METHOD_LABELS = {
    exact: "exact match",
    phrase: "phrase match",
    fuzzy: "fuzzy match — spelling variant"
  };

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function codeSpan(value) {
    return el("span", "code", value);
  }

  /* One assist instance per mount. */
  function Assist(mount) {
    var root = mount.closest("form") || mount.parentElement || document;
    this.mount = mount;
    this.source = root.querySelector("[data-coding-source]");
    this.finalTerm = root.querySelector("[data-coding-final-term]");
    this.finalCode = root.querySelector("[data-coding-final-code]");
    this.requestId = 0;
    this.pending = null;     /* AbortController for the in-flight request */
    this.timer = null;

    if (!this.source) return;  /* nothing to read — stay hidden, stay silent */

    var self = this;
    if (this.source.tagName === "TEXTAREA" || this.source.type === "text") {
      this.source.addEventListener("input", function () { self.schedule(); });
    }
    if (mount.hasAttribute("data-coding-autoload")) {
      this.run();
    }
  }

  Assist.prototype.schedule = function () {
    var self = this;
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(function () { self.run(); }, DEBOUNCE_MS);
  };

  Assist.prototype.narrative = function () {
    return (this.source.value || "").trim();
  };

  Assist.prototype.run = function () {
    var text = this.narrative();
    if (text.length < MIN_LEN) {
      this.abort();
      this.mount.hidden = true;
      return;
    }
    this.abort();
    this.requestId += 1;
    var id = this.requestId;
    var controller = new AbortController();
    this.pending = controller;

    this.renderChecking();

    var self = this;
    window.fetch("/api/pv/code", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken()
      },
      body: JSON.stringify({ narrative: text }),
      signal: controller.signal,
      credentials: "same-origin"
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      if (id !== self.requestId) return;  /* a newer request owns the mount */
      self.render(data.suggestions || []);
    }).catch(function (err) {
      if (err && err.name === "AbortError") return;
      if (id !== self.requestId) return;
      self.renderError();
    });
  };

  Assist.prototype.abort = function () {
    if (this.pending) {
      this.pending.abort();
      this.pending = null;
    }
  };

  Assist.prototype.reset = function () {
    this.mount.textContent = "";
    this.mount.hidden = false;
  };

  Assist.prototype.renderChecking = function () {
    this.reset();
    var line = el("p", "assist-line");
    line.appendChild(el("span", "label", "AI coding assist"));
    line.appendChild(el("span", "assist-status", "Checking the curated vocabulary…"));
    this.mount.appendChild(line);
  };

  Assist.prototype.render = function (suggestions) {
    this.reset();
    var self = this;
    var writable = this.finalTerm && this.finalCode;

    var line = el("p", "assist-line");
    line.appendChild(el("span", "label", "AI coding assist"));
    if (suggestions.length) {
      line.appendChild(el("span", "assist-status",
        writable ? "Choose a suggestion to pre-fill the final coding, or type your own."
                 : "Advisory only — a Safety Officer confirms or corrects this at review."));
    }
    this.mount.appendChild(line);

    if (!suggestions.length) {
      this.mount.appendChild(el("p", "assist-none",
        "No match above the confidence floor. The event can still be filed — " +
        "it stays Uncoded rather than being guessed into the wrong term, and " +
        "coding is completed at Safety Officer review."));
      return;
    }

    var list = el("ul", "assist-list");
    suggestions.forEach(function (s) {
      var item = el("li", "assist-item");

      var head;
      if (writable) {
        head = el("button", "assist-apply");
        head.type = "button";
        head.setAttribute("aria-label", "Use suggestion " + s.term + " (" + s.code + ")");
        head.addEventListener("click", function () {
          self.finalTerm.value = s.term;
          self.finalCode.value = s.code;
          self.finalTerm.focus();
          self.markChosen(item, s);
        });
      } else {
        head = el("span", "assist-apply assist-apply-static");
      }
      head.appendChild(el("strong", null, s.term));
      head.appendChild(codeSpan(s.code));
      item.appendChild(head);

      item.appendChild(el("span", "assist-basis",
        (METHOD_LABELS[s.method] || s.method) + " · confidence " + s.confidence +
        " · " + (s.soc || "")));
      list.appendChild(item);
    });
    this.mount.appendChild(list);

    this.mount.appendChild(el("p", "assist-note",
      "A confidence score is a vocabulary-match number, not a probability of " +
      "diagnosis. Vocabulary: curated demonstration set (app/terms.csv), not MedDRA."));
  };

  Assist.prototype.markChosen = function (chosenItem, suggestion) {
    var items = this.mount.querySelectorAll(".assist-item");
    for (var i = 0; i < items.length; i += 1) items[i].classList.remove("assist-chosen");
    chosenItem.classList.add("assist-chosen");
    var status = this.mount.querySelector(".assist-status");
    if (status) {
      status.textContent = "Pre-filled “" + suggestion.term + "” — confirm or correct, then submit.";
    }
  };

  Assist.prototype.renderError = function () {
    this.reset();
    var line = el("p", "assist-line");
    line.appendChild(el("span", "label", "AI coding assist"));
    this.mount.appendChild(line);
    this.mount.appendChild(el("p", "assist-none assist-error",
      "Assist unavailable right now — this changes nothing about filing: " +
      "the event saves as Uncoded and a Safety Officer codes it at review."));
  };

  function boot() {
    var mounts = document.querySelectorAll("[data-coding-assist]");
    for (var i = 0; i < mounts.length; i += 1) new Assist(mounts[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
