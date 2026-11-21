#!/usr/bin/env python3
"""PrintView Admin window: shows the admin website (http://127.0.0.1:8095) in its own window,
using the WebKit engine library. Not a browser: no address bar, no other sites, nothing else installed."""
import os
# The Pi's graphics driver draws WebKit pages scrambled with its newer buffer-sharing renderer; use the plain one.
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2  # noqa: E402

URL = "http://127.0.0.1:8095/"


def main():
    win = Gtk.Window(title="PrintView Admin")
    win.set_default_size(1400, 900)
    ctx = WebKit2.WebContext.get_default()
    view = WebKit2.WebView.new_with_context(ctx)
    s = view.get_settings()
    s.set_enable_webgl(True)
    s.set_enable_javascript(True)
    s.set_javascript_can_open_windows_automatically(True)

    # links that open a new tab (Slicer, videos) open in a second window of this app
    def new_window(_v, _nav):
        w2 = Gtk.Window(title="PrintView")
        w2.set_default_size(1400, 900)
        v2 = WebKit2.WebView.new_with_related_view(view)
        v2.connect("ready-to-show", lambda *_: w2.show_all())
        w2.add(v2)
        return v2
    view.connect("create", new_window)

    # downloads (timelapses, files) go to ~/Downloads
    def on_download(_ctx, dl):
        import os
        def decide(d, name):
            d.set_destination("file://" + os.path.join(os.path.expanduser("~/Downloads"), name))
            return True
        dl.connect("decide-destination", decide)
    ctx.connect("download-started", on_download)

    view.load_uri(URL)
    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
