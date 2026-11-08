package dev.printwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Shared plumbing for the newer screens: page scaffold, background calls, images, dialogs. */
abstract class Base extends Activity {
    final Handler ui = new Handler(Looper.getMainLooper());
    final ExecutorService net = Executors.newFixedThreadPool(3);
    LinearLayout root;

    interface Done<T> { void run(T value, String error); }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(Ui.BG);
        getWindow().setNavigationBarColor(Ui.BG);
    }

    /** Scroll page with a back button and title; returns the content column. */
    LinearLayout page(String back, String title) {
        Context c = this;
        ScrollView sv = new ScrollView(c);
        sv.setBackgroundColor(Ui.BG);
        root = new LinearLayout(c);
        root.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 14);
        root.setPadding(p, Ui.dp(c, 8), p, Ui.dp(c, 28));
        sv.addView(root);
        LinearLayout head = Ui.row(c);
        head.setPadding(0, Ui.dp(c, 6), 0, Ui.dp(c, 4));
        android.widget.ImageView bk = Ui.iconButton(c, "chev_l", Ui.TEXT, Ui.SURFACE);
        bk.setContentDescription(back);
        bk.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { finish(); } });
        head.addView(bk, new LinearLayout.LayoutParams(Ui.dp(c, 42), Ui.dp(c, 42)));
        TextView t = Ui.text(c, title, 22, Ui.TEXT, true);
        t.setSingleLine(true);
        t.setEllipsize(android.text.TextUtils.TruncateAt.END);
        t.setPadding(Ui.dp(c, 12), 0, 0, 0);
        head.addView(t, Ui.weight(1));
        root.addView(head);
        setContentView(sv);
        return root;
    }

    static String q(String s) {
        try { return URLEncoder.encode(s, "UTF-8"); } catch (Exception e) { return s; }
    }

    void getJson(final String path, final Done<JSONObject> done) {
        net.execute(new Runnable() {
            public void run() {
                JSONObject j = null; String err = null;
                try {
                    Api.Resp r = Api.get(Base.this, path, null, 60000);
                    String txt = r.text().trim();
                    j = new JSONObject(txt.startsWith("[") ? "{\"list\":" + txt + "}" : txt);
                    if (r.code != 200) { err = j.optString("error", "HTTP " + r.code); j = null; }
                } catch (Exception e) { err = "Can't reach PrintWatch"; }
                final JSONObject fj = j; final String fe = err;
                ui.post(new Runnable() { public void run() { if (!isFinishing()) done.run(fj, fe); } });
            }
        });
    }

    void post(final String path, final String json, final Done<JSONObject> done) {
        net.execute(new Runnable() {
            public void run() {
                JSONObject j = null; String err = null;
                try {
                    Api.Resp r = Api.post(Base.this, path, json);
                    j = new JSONObject(r.text());
                    if (!j.optBoolean("ok", r.code == 200)) err = j.optString("error", "HTTP " + r.code);
                } catch (Exception e) { err = "Can't reach PrintWatch"; }
                final JSONObject fj = j; final String fe = err;
                ui.post(new Runnable() { public void run() { if (!isFinishing()) done.run(fj, fe); } });
            }
        });
    }

    /** Fire a /api/cmd and toast the result. */
    void cmd(String json, final String okMsg) {
        post("/api/cmd", json, new Done<JSONObject>() {
            public void run(JSONObject v, String e) { toast(e == null ? okMsg : e); }
        });
    }

    void image(final String path, final ImageView iv) {
        net.execute(new Runnable() {
            public void run() {
                try {
                    Api.Resp r = Api.get(Base.this, path, null, 60000);
                    if (r.code == 200 && r.body != null) {
                        final Bitmap bm = BitmapFactory.decodeByteArray(r.body, 0, r.body.length);
                        ui.post(new Runnable() { public void run() { iv.setImageBitmap(bm); } });
                    }
                } catch (Exception ignored) { }
            }
        });
    }

    void confirm(String title, String msg, String ok, final Runnable action) {
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(title).setMessage(msg).setNegativeButton("Cancel", null)
                .setPositiveButton(ok, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) { action.run(); }
                }).show();
    }

    void toast(String m) {
        Toast.makeText(this, m, Toast.LENGTH_SHORT).show();
    }

    TextView note(LinearLayout parent, String s) {
        TextView t = Ui.text(this, s, 13, Ui.MUTED, false);
        t.setPadding(0, Ui.dp(this, 10), 0, Ui.dp(this, 10));
        parent.addView(t);
        return t;
    }

    ImageView thumb(int wDp, int hDp) {
        ImageView iv = new ImageView(this);
        iv.setBackground(Ui.box(this, Color.BLACK, 0, 10));
        iv.setClipToOutline(true);
        iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
        iv.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(this, wDp), Ui.dp(this, hDp)));
        return iv;
    }

    static String size(long b) {
        if (b > 1_000_000) return String.format("%.1f MB", b / 1e6);
        if (b > 1000) return (b / 1000) + " KB";
        return b + " B";
    }
}
