/* Runs first, before the big engine data at the end of the slicer page has arrived.
   Over the internet the page can still be downloading when Slice is pressed, and slicing then fails with
   "atob ... not correctly encoded". Until the whole page is in, Slice waits and then starts by itself. */
(function () {
  "use strict";
  var waiting = false, note = null;
  document.addEventListener("click", function (ev) {
    var t = ev.target && ev.target.closest && ev.target.closest("#slice, #mi-slice");
    if (!t || document.readyState === "complete") return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    if (waiting) return;
    waiting = true;
    note = document.createElement("div");
    note.textContent = "The slicer is still downloading its engine. Slicing starts by itself as soon as it's done.";
    note.style.cssText = "position:fixed;left:50%;top:70px;transform:translateX(-50%);z-index:99999;max-width:min(460px,92vw);" +
      "background:#fff;color:#222;border:1px solid #ccc;border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,.35);padding:14px 16px;font:14px/1.45 system-ui,sans-serif";
    document.body.appendChild(note);
    window.addEventListener("load", function () {
      if (note) note.remove();
      setTimeout(function () { var b = document.getElementById("slice"); if (b && !b.disabled) b.click(); }, 1200);
    });
  }, true);
})();
