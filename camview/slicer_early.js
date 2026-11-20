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

/* Engine diagnostics: if the slicing engine fails, say why instead of "Engine worker failed: unknown". */
(function () {
  "use strict";
  var detail = [];
  window.__pvEngineDetail = detail;
  if (typeof WebAssembly !== "object") detail.push("This browser has WebAssembly turned off, and the slicer's engine needs it.");
  var OrigBlob = window.Blob;
  window.Blob = function (parts, opts) {
    try {
      if (parts && parts.length && typeof parts[parts.length - 1] === "string" && parts[parts.length - 1].indexOf("SecondSlice(") >= 0) {
        parts = ["self.addEventListener('unhandledrejection', function (e) { var r = e.reason; postMessage({ t: 'log', s: 'PV-ENGINE-ERROR ' + (r && (r.stack || r.message) || r) }); });\n" +
                 "self.addEventListener('error', function (e) { postMessage({ t: 'log', s: 'PV-ENGINE-ERROR ' + (e.message || 'error') + ' @' + (e.lineno || '?') }); });\n"].concat(parts);
      }
    } catch (e) { }
    return new OrigBlob(parts, opts);
  };
  window.Blob.prototype = OrigBlob.prototype;
  var origLog = console.log;
  console.log = function () {
    try { var a = arguments; if (a[0] === "[orca]" && String(a[1]).indexOf("PV-ENGINE-ERROR") === 0) detail.push(String(a[1]).slice(16)); } catch (e) { }
    return origLog.apply(console, arguments);
  };
  var OrigWorker = window.Worker;
  window.Worker = function (url, o) {
    var w = new OrigWorker(url, o);
    w.addEventListener("error", function (e) { detail.push("Worker error: " + (e.message || "the engine couldn't start in this browser") + (e.lineno ? " (line " + e.lineno + ")" : "")); });
    return w;
  };
  window.Worker.prototype = OrigWorker.prototype;
  var origAlert = window.alert;
  window.alert = function (msg) {
    if (/Engine worker failed|atob|Slice failed/.test(String(msg))) {
      var extra = detail.length ? "\n\nDetails:\n" + detail.slice(-4).join("\n") : "";
      msg = String(msg) + extra + "\n\nIf you use Microsoft Edge: Settings > Privacy > 'Enhance your security on the web' can turn off what the engine needs. Add this site as an exception, or try Chrome. Then reload this page.";
    }
    return origAlert.call(window, msg);
  };
})();
