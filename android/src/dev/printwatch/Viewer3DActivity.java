package dev.printwatch;

import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.util.HashMap;
import java.util.Map;

/** Full-screen 3D toolpath of one plate. The viewer is the same code as the web link (assets/viewer3d.html);
 *  its data request is answered here through the app's normal (pinned, paired) connection. */
public class Viewer3DActivity extends Base {
    static final String ORIGIN = "https://printview.local/";

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        final Context c = this;
        final String path = getIntent().getStringExtra("path");
        final int plate = getIntent().getIntExtra("plate", 1);

        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackgroundColor(Ui.BG);
        LinearLayout head = Ui.row(c);
        int p = Ui.dp(c, 14);
        head.setPadding(p, Ui.dp(c, 14), p, Ui.dp(c, 4));
        android.widget.ImageView bk = Ui.iconButton(c, "chev_l", Ui.TEXT, Ui.SURFACE);
        bk.setContentDescription("Back");
        bk.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { finish(); } });
        head.addView(bk, new LinearLayout.LayoutParams(Ui.dp(c, 42), Ui.dp(c, 42)));
        TextView t = Ui.text(c, getIntent().getStringExtra("title") + " · plate " + plate, 20, Ui.TEXT, true);
        t.setSingleLine(true);
        t.setEllipsize(android.text.TextUtils.TruncateAt.END);
        t.setPadding(Ui.dp(c, 12), 0, 0, 0);
        head.addView(t, Ui.weight(1));
        col.addView(head);

        WebView w = new WebView(c);
        w.setBackgroundColor(Ui.BG);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, String u) { return true; }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                String u = r.getUrl().toString();
                if (!u.startsWith(ORIGIN + "toolpath")) return null;
                Map<String, String> hdr = new HashMap<>();
                hdr.put("Access-Control-Allow-Origin", "*");
                try {   // runs on a WebView background thread, so a blocking download is fine here
                    HttpURLConnection h = Api.stream(c, "/api/files/gcode3d?plate=" + plate + "&path=" + q(path));
                    h.setReadTimeout(180000);
                    int code = h.getResponseCode();
                    InputStream in = code < 400 ? h.getInputStream() : h.getErrorStream();
                    String type = code < 400 ? "application/octet-stream" : "application/json";
                    return new WebResourceResponse(type, null, code, code < 400 ? "OK" : "Error", hdr,
                            in != null ? in : new ByteArrayInputStream(new byte[0]));
                } catch (Exception e) {
                    String msg = "{\"error\":\"Can't reach PrintView: " + String.valueOf(e.getMessage()).replace("\"", "'") + "\"}";
                    return new WebResourceResponse("application/json", "utf-8", 502, "Error", hdr,
                            new ByteArrayInputStream(msg.getBytes()));
                }
            }
        });
        col.addView(w, new LinearLayout.LayoutParams(-1, 0, 1f));
        setContentView(col);
        try {
            InputStream in = getAssets().open("viewer3d.html");
            byte[] buf = new byte[in.available()];
            int n = 0;
            while (n < buf.length) { int r = in.read(buf, n, buf.length - n); if (r < 0) break; n += r; }
            in.close();
            w.loadDataWithBaseURL(ORIGIN, new String(buf, 0, n, "UTF-8"), "text/html", "utf-8", null);
        } catch (Exception e) {
            w.loadData("Viewer missing", "text/plain", "utf-8");
        }
    }
}
