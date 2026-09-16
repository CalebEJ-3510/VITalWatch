/* VITalWatch — public landing, progressive enhancement only.
   ---------------------------------------------------------------------------
   Nothing on this page depends on this file: the drawer is a <details>
   element, the role selector is radio inputs, the workflow path is an ordered
   list, the fixture clock is labelled static text, and every [data-reveal]
   element is visible unless this script marks the document "ljs" (the CSS
   hides nothing without that class, and hides nothing at all under
   prefers-reduced-motion). This file only refines what already works:

     1. Escape closes the drawer and returns focus; choosing a destination
        closes it too.
     2. [data-reveal] elements fade/slide in as they enter the viewport
        (IntersectionObserver; browsers without it get everything shown).
     3. The labelled fixture clock ticks upward from its printed value.
     4. The evidence-chain hashes flicker once when the chain scrolls in.
     5. The masthead gains a condensed state and a scroll-position hairline.

   Reduced motion: only enhancements 1 and 5's class toggle run — nothing
   autonomously moves (§6.1.3, §13.3). */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* --- 1. the drawer (works without this; this refines it) -------------------- */
  var drawer = document.getElementById("nav-drawer");
  if (drawer) {
    var trigger = drawer.querySelector("summary");

    drawer.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && drawer.open) {
        drawer.open = false;
        if (trigger) trigger.focus();
      }
    });

    drawer.addEventListener("click", function (event) {
      var link = event.target.closest("a");
      if (link && drawer.open) drawer.open = false;
    });

    document.addEventListener("click", function (event) {
      if (drawer.open && !drawer.contains(event.target)) drawer.open = false;
    });
  }

  /* --- 2. scroll reveals ---------------------------------------------------------
     Mark the document FIRST (deferred scripts run before first paint in
     practice): from here the CSS may pre-hide [data-reveal] until .l-in.
     Without IntersectionObserver, reveal everything immediately — a browser
     that cannot observe cannot be allowed to hide content forever. */
  var root = document.documentElement;
  var revealed = document.querySelectorAll("[data-reveal]");

  if (!reduceMotion) {
    root.classList.add("ljs");

    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("l-in");
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
      revealed.forEach(function (el) { io.observe(el); });
    } else {
      revealed.forEach(function (el) { el.classList.add("l-in"); });
    }
  }

  /* --- 3. the fixture clock ticks ------------------------------------------------
     The hero preview is a labelled synthetic fixture ("values are
     illustrative"); the ticking adds life without changing what the value
     claims to be. Static text remains the no-JS and reduced-motion truth. */
  var tick = document.querySelector("[data-tick]");
  if (tick && !reduceMotion) {
    var start = tick.getAttribute("data-tick") || "0:00";
    var parts = start.split(":");
    var elapsed = (parseInt(parts[0], 10) || 0) * 3600 + (parseInt(parts[1], 10) || 0) * 60;
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    window.setInterval(function () {
      elapsed += 1;
      var h = Math.floor(elapsed / 3600);
      var m = Math.floor((elapsed % 3600) / 60);
      var s = elapsed % 60;
      tick.textContent = h + ":" + pad(m) + ":" + pad(s);
    }, 1000);
  }

  /* --- 4. the hash flicker ----------------------------------------------------------
     Each chain hash cycles through random hex once, then settles on its true
     printed value — the record becoming tamper-evident, told in motion. The
     settled text is identical to the static markup, so the enhancement never
     changes what the page says. */
  var hashes = document.querySelectorAll("[data-hash]");
  if (hashes.length && !reduceMotion && "IntersectionObserver" in window) {
    var HEX = "0123456789abcdef";
    var scramble = function (el) {
      var finalText = el.getAttribute("data-hash");
      var frame = 0;
      var timer = window.setInterval(function () {
        frame += 1;
        if (frame >= 14) {
          window.clearInterval(timer);
          el.textContent = finalText;
          return;
        }
        el.textContent = finalText.replace(/[0-9a-f]/g, function () {
          return HEX.charAt(Math.floor(Math.random() * 16));
        });
      }, 46);
    };
    var hashIO = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          hashes.forEach(scramble);
          hashIO.disconnect();
        }
      });
    }, { threshold: 0.3 });
    if (hashes[0]) hashIO.observe(hashes[0].closest(".l-chain-stage") || hashes[0]);
  }

  /* --- 5. masthead state + scroll hairline -------------------------------------------
     The hairline is the reference-line motif turned on the page itself: where
     you are against the whole. rAF-throttled; no layout reads beyond scroll
     geometry. Runs regardless of motion preference because it only reflects
     scroll position, like a scrollbar — it animates nothing autonomously. */
  var masthead = document.querySelector(".l-masthead");
  var progress = document.querySelector(".l-progress");
  if (masthead) {
    var scheduled = false;
    var onScroll = function () {
      if (scheduled) return;
      scheduled = true;
      window.requestAnimationFrame(function () {
        scheduled = false;
        var y = window.scrollY || window.pageYOffset || 0;
        masthead.classList.toggle("l-scrolled", y > 8);
        if (progress) {
          var doc = document.documentElement;
          var max = doc.scrollHeight - window.innerHeight;
          progress.style.transform = "scaleX(" + (max > 0 ? Math.min(y / max, 1) : 0) + ")";
        }
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }
})();
