/* PrintView bridge for the slicer: adds "Send to printer" next to "Export plate sliced file".
   It takes the same .gcode.3mf the export would download and uploads it to the printer's SD card
   through PrintView, then offers to open it in PrintView to pick filament slots and start it. */
(function () {
  "use strict";
  var BASE = location.pathname.replace(/\/slicer\/?$/, "");
  var sendMode = false;
  var origClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (sendMode && this.download && /\.gcode\.3mf$/i.test(this.download)) {
      sendMode = false;
      var name = this.download, href = this.href;
      fetch(href).then(function (r) { return r.blob(); }).then(function (b) { upload(b, name); })
        .catch(function () { show("Couldn't read the sliced file. Slice again and retry.", true); });
      return;
    }
    return origClick.call(this);
  };

  var box;
  function show(html, isErr, actions) {
    if (!box) {
      box = document.createElement("div");
      box.style.cssText = "position:fixed;left:50%;top:70px;transform:translateX(-50%);z-index:99999;max-width:min(460px,92vw);" +
        "background:var(--panel,#fff);color:var(--text,#222);border:1px solid var(--line,#ccc);border-radius:8px;" +
        "box-shadow:0 8px 30px rgba(0,0,0,.35);padding:14px 16px;font:14px/1.45 system-ui,sans-serif";
      document.body.appendChild(box);
    }
    box.innerHTML = "";
    var t = document.createElement("div");
    t.textContent = html;
    if (isErr) t.style.color = "var(--err,#d33)";
    box.appendChild(t);
    var row = document.createElement("div");
    row.style.cssText = "display:flex;gap:8px;justify-content:flex-end;margin-top:12px";
    (actions || []).forEach(function (a) {
      var b = document.createElement("button");
      b.textContent = a[0];
      if (a[2]) b.className = "pri";
      b.onclick = a[1];
      row.appendChild(b);
    });
    var c = document.createElement("button");
    c.textContent = "Close";
    c.onclick = function () { box.remove(); box = null; };
    row.appendChild(c);
    box.appendChild(row);
  }

  function upload(blob, name) {
    var x = new XMLHttpRequest();
    x.open("POST", BASE + "/api/upload?name=" + encodeURIComponent(name));
    x.withCredentials = true;
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.setRequestHeader("X-PW", "1");
    x.upload.onprogress = function (e) {
      if (e.lengthComputable) show("Sending " + name + " to the printer... " + Math.round(e.loaded / e.total * 100) + "%");
    };
    x.onload = function () {
      var j = {};
      try { j = JSON.parse(x.responseText); } catch (e) { }
      if (x.status === 200 && j.ok) {
        show("Sent. The Pi is copying " + j.name + " to the printer's SD card now (a big file can take a few minutes). Then open it in PrintView to pick the filament slots and start, schedule or queue it.", false,
          [["Open in PrintView", function () { location.href = BASE + "/?open=" + encodeURIComponent(j.path); }, true]]);
      } else if (x.status === 401) {
        show("Sending to the printer needs the general code. Open PrintView, tap Enter code, then come back and send again.", true,
          [["Open PrintView", function () { window.open(BASE + "/", "_blank"); }, true]]);
      } else if (x.status === 423) {
        show("Controls are frozen by the owner, so nothing can be sent right now.", true);
      } else {
        show("Couldn't send: " + (j.error || ("HTTP " + x.status)), true);
      }
    };
    x.onerror = function () { show("Couldn't send: connection lost.", true); };
    show("Sending " + name + " to the printer... 0%");
    x.send(blob);
  }

  function addButton() {
    var exp = document.getElementById("export3mf");
    if (!exp || document.getElementById("pvSend")) return;
    var wrap = document.createElement("div");
    wrap.className = "sbtn";
    wrap.style.marginLeft = "6px";
    var b = document.createElement("button");
    b.id = "pvSend";
    b.className = "pri";
    b.textContent = "Send to printer";
    b.title = "Put the sliced file on the printer's SD card through PrintView";
    b.disabled = exp.disabled;
    b.onclick = function () {
      if (exp.disabled) return;
      sendMode = true;
      exp.click();
      setTimeout(function () { sendMode = false; }, 15000);
    };
    wrap.appendChild(b);
    exp.parentNode.parentNode.insertBefore(wrap, exp.parentNode.nextSibling);
    new MutationObserver(function () { b.disabled = exp.disabled; }).observe(exp, {attributes: true, attributeFilter: ["disabled"]});
    var back = document.createElement("a");
    back.href = BASE + "/";
    back.textContent = "PrintView";
    back.title = "Back to PrintView";
    back.style.cssText = "margin-left:10px;align-self:center;color:var(--acc,#009688);font-weight:600;text-decoration:none";
    exp.parentNode.parentNode.insertBefore(back, wrap.nextSibling);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addButton); else addButton();

  // If the engine tried to start before the whole page had arrived, start it again now that it has.
  window.addEventListener("load", function () {
    try {
      /* global enginePromise, engineW, loadEngine */
      if (typeof loadEngine === "function" && !engineW) { enginePromise = null; loadEngine().catch(function () { }); }
    } catch (e) { }
  });
})();
