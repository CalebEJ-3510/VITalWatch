/* VITalWatch — command palette (Phase 3, prompt.md §7.4).
 *
 * Progressive enhancement over the authenticated shell: the rail remains the
 * complete navigation without this script, and the trigger stays hidden unless
 * this file executes. Behaviour contract:
 *
 * - Open via the shell trigger, Ctrl+K / Cmd+K (platform-detected), or "/"
 *   outside editable fields. Escape closes and returns focus to the trigger.
 * - Debounced search (220ms) against GET /api/search; in-flight requests are
 *   aborted when newer input arrives so stale responses never paint.
 * - Arrow keys move, Enter opens, full result count is announced via an
 *   aria-live region; idle / loading / empty / error are four distinct states
 *   (§10.1), not four spellings of a spinner.
 * - Results arrive permission-filtered from the server; nothing is hidden
 *   client-side after fetch, because there is nothing unsafe to hide.
 */
(function () {
  "use strict";

  var palette = document.getElementById("palette");
  var trigger = document.querySelector("[data-palette-open]");
  if (!palette || !trigger) return;

  var input = document.getElementById("palette-input");
  var status = document.getElementById("palette-status");
  var results = document.getElementById("palette-results");
  var hint = document.querySelector("[data-palette-hint]");

  var isMac = /Mac|iPhone|iPad/.test(navigator.platform || "");
  if (hint) hint.textContent = isMac ? "⌘K" : "Ctrl K";

  /* The trigger and palette only exist as controls once JS is running. */
  trigger.hidden = false;

  var lastTrigger = null;
  var activeIndex = -1;
  var currentLinks = [];
  var debounceTimer = null;
  var inFlight = null;

  function openPalette() {
    lastTrigger = document.activeElement;
    palette.hidden = false;
    document.body.style.overflow = "hidden";
    input.value = "";
    setIdle();
    window.setTimeout(function () { input.focus(); }, 0);
  }

  function closePalette() {
    palette.hidden = true;
    document.body.style.overflow = "";
    abortInFlight();
    if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
  }

  function setIdle() {
    activeIndex = -1;
    currentLinks = [];
    results.innerHTML = "";
    status.textContent = "Type at least 2 characters to search.";
  }

  function setLoading() {
    status.textContent = "Searching…";
  }

  function setEmpty(q) {
    results.innerHTML = "";
    status.textContent = 'No matches for "' + q + '". Identifiers, coded terms and ' +
      "audit sequence numbers are searchable; clinical narratives are not.";
  }

  function setError() {
    results.innerHTML = "";
    status.textContent = "Search failed — the page's other navigation is unaffected. " +
      "Check your connection and try again.";
  }

  function abortInFlight() {
    if (inFlight) { inFlight.abort(); inFlight = null; }
    if (debounceTimer) { window.clearTimeout(debounceTimer); debounceTimer = null; }
  }

  function render(data) {
    activeIndex = -1;
    currentLinks = [];
    results.innerHTML = "";
    if (!data.groups || data.groups.length === 0) { setEmpty(data.q); return; }

    data.groups.forEach(function (group) {
      var heading = document.createElement("p");
      heading.className = "palette-group";
      heading.textContent = group.label;
      results.appendChild(heading);

      group.results.forEach(function (item) {
        var a = document.createElement("a");
        a.className = "palette-item";
        a.href = item.href;
        a.setAttribute("role", "option");

        var title = document.createElement("span");
        title.className = "palette-item-title";
        title.textContent = item.title;
        var sub = document.createElement("span");
        sub.className = "palette-item-sub";
        sub.textContent = item.sub;

        a.appendChild(title);
        a.appendChild(sub);
        results.appendChild(a);
        currentLinks.push(a);
      });
    });

    status.textContent = data.total + (data.total === 1 ? " result" : " results") +
      ' for "' + data.q + '" — ' + (data.scope_note ||
      "limited to records your role may read.");
  }

  function search(q) {
    abortInFlight();
    if (q.trim().length < 2) { setIdle(); return; }
    setLoading();
    debounceTimer = window.setTimeout(function () {
      var controller = new AbortController();
      inFlight = controller;
      fetch("/api/search?q=" + encodeURIComponent(q.trim()), {
        headers: { "Accept": "application/json" },
        signal: controller.signal,
        credentials: "same-origin"
      }).then(function (res) {
        if (!res.ok) throw new Error("search failed: " + res.status);
        return res.json();
      }).then(function (data) {
        if (inFlight !== controller) return; // a newer request owns the panel
        inFlight = null;
        render(data);
      }).catch(function (err) {
        if (err && err.name === "AbortError") return;
        if (inFlight === controller) inFlight = null;
        setError();
      });
    }, 220);
  }

  function move(delta) {
    if (!currentLinks.length) return;
    activeIndex = (activeIndex + delta + currentLinks.length) % currentLinks.length;
    currentLinks.forEach(function (link, i) {
      link.classList.toggle("palette-item-active", i === activeIndex);
      if (i === activeIndex) {
        link.setAttribute("aria-selected", "true");
        link.scrollIntoView({ block: "nearest" });
      } else {
        link.removeAttribute("aria-selected");
      }
    });
  }

  trigger.addEventListener("click", openPalette);
  palette.querySelector("[data-palette-close]").addEventListener("click", closePalette);

  input.addEventListener("input", function () { search(input.value); });
  input.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
    else if (event.key === "Enter") {
      if (activeIndex >= 0 && currentLinks[activeIndex]) {
        event.preventDefault();
        window.location.href = currentLinks[activeIndex].href;
      }
    }
  });

  document.addEventListener("keydown", function (event) {
    var editable = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) ||
      event.target.isContentEditable;
    if (!palette.hidden) {
      if (event.key === "Escape") { event.preventDefault(); closePalette(); }
      return;
    }
    if (editable) return;
    if ((event.key === "k" || event.key === "K") && (event.ctrlKey || event.metaKey)) {
      event.preventDefault(); openPalette();
    } else if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault(); openPalette();
    }
  });
})();
