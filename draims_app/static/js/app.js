// DRAIMS client-side behaviour. Kept in this file because the Content-Security-Policy blocks inline scripts.
(function () {
  "use strict";

  // Browser-side validation: show Bootstrap messages instead of submitting an invalid form.
  document.querySelectorAll("form.needs-validation").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      var valid = form.checkValidity();
      var unique = itemsAreUnique(form);      // run both checks so every message shows at once
      if (!valid || !unique) {
        e.preventDefault();
        e.stopPropagation();
      }
      form.classList.add("was-validated");
    });
  });

  // Ask before actions that cannot be undone (close disaster, cancel request, run allocation).
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // Relief request: add / remove item rows and block duplicate items.
  var table = document.getElementById("item-table");
  if (table) {
    var body = table.querySelector("tbody");
    document.getElementById("add-row").addEventListener("click", function () {
      var rows = body.querySelectorAll(".item-row");
      if (rows.length >= 15) return;
      var copy = rows[0].cloneNode(true);
      copy.querySelector("select").value = "";
      copy.querySelector("input").value = "";
      body.appendChild(copy);
    });
    body.addEventListener("click", function (e) {
      var btn = e.target.closest(".remove-row");
      if (!btn) return;
      var rows = body.querySelectorAll(".item-row");
      if (rows.length > 1) btn.closest("tr").remove();
    });
  }

  function itemsAreUnique(form) {
    var box = document.getElementById("dup-error");
    if (!box || form.id !== "request-form") return true;
    var seen = {}, dup = false;
    form.querySelectorAll("select[name=item_id]").forEach(function (s) {
      if (s.value && seen[s.value]) dup = true;
      seen[s.value] = true;
    });
    box.classList.toggle("d-none", !dup);
    return !dup;
  }

  // Dispatch page: select-all checkbox and a live count of ticked rows.
  var all = document.getElementById("select-all");
  var count = document.getElementById("sel-count");
  function showCount() {
    if (!count) return;
    var n = document.querySelectorAll(".row-check:checked").length;
    count.textContent = n ? n + " selected" : "Tick the rows to update.";
  }
  if (all) {
    all.addEventListener("change", function () {
      document.querySelectorAll(".row-check").forEach(function (c) { c.checked = all.checked; });
      showCount();
    });
  }
  document.querySelectorAll(".row-check").forEach(function (c) { c.addEventListener("change", showCount); });
})();
