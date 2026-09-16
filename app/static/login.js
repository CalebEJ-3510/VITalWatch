/* VITalWatch — sign-in, progressive enhancement only (Phase 6).
   ---------------------------------------------------------------------------
   Nothing on this page depends on this file: the form submits without it, and
   every demo credential is printed on its chip for manual entry. What this
   adds is exactly one behavior — a chip FILLS the form. It never submits,
   never signs in, and never touches the network: the account, authenticated
   by the server, remains the only source of permission. */
(function () {
  "use strict";

  var form = document.getElementById("signin-form");
  if (!form) return;

  var username = document.getElementById("username");
  var password = document.getElementById("password");
  var submit = document.getElementById("signin-submit");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".auth-chip"));
  if (!username || !password || !submit || !chips.length) return;

  /* Mark the chip whose credentials currently sit in the form. Filling by
     hand to exactly match a demo account marks it too — the label describes
     the form's contents, never a granted permission. */
  function syncChips() {
    chips.forEach(function (chip) {
      var on = username.value === chip.getAttribute("data-username") &&
               password.value === chip.getAttribute("data-password");
      chip.classList.toggle("auth-chip-on", on);
      chip.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      username.value = chip.getAttribute("data-username") || "";
      password.value = chip.getAttribute("data-password") || "";
      syncChips();
      /* Move focus to the submit button: one tap fills, Enter signs in. The
         focus ring is visible, so the keyboard user sees where they landed. */
      submit.focus();
    });
  });

  form.addEventListener("input", syncChips);

  /* Pending state: the button states what is happening and cannot be
     double-submitted while the round trip is in flight. */
  form.addEventListener("submit", function () {
    submit.disabled = true;
    submit.textContent = "Signing in…";
  });

  /* Escape key returns to home page */
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      window.location.href = "/";
    }
  });
})();
