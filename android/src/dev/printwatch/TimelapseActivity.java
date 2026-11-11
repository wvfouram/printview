package dev.printwatch;

import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/** Timelapse videos on the printer's SD card: play or save to the phone. */
public class TimelapseActivity extends Base {
    private LinearLayout list, piList;
    private TextView status, piStatus;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Live", "Timelapses");
        Button refresh = Ui.button(this, "Refresh", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        refresh.setTextSize(14);
        refresh.setMinHeight(Ui.dp(this, 44));
        refresh.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { load(true); } });
        p.addView(refresh);
        p.addView(Ui.heading(this, "Made by the Pi (per layer)"));
        piStatus = note(p, "Loading...");
        piList = new LinearLayout(this);
        piList.setOrientation(LinearLayout.VERTICAL);
        p.addView(piList);
        p.addView(Ui.heading(this, "From the printer's SD card"));
        status = note(p, "Reading the SD card...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        note(p, "Turn on Timelapse when starting a print. Videos download into the app (at home or away), then play or save. Transfers run at SD-card speed.");
        load(false);
    }

    private void loadPi() {
        getJson("/api/timelapse", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                piList.removeAllViews();
                if (e != null) { piStatus.setText(e); return; }
                JSONArray a = v.optJSONArray("items");
                int n = a == null ? 0 : a.length();
                piStatus.setText(n == 0 ? "None yet. The Pi records one frame per layer of every print." : n + " timelapse" + (n == 1 ? "" : "s"));
                boolean busy = false;
                for (int i = 0; i < n; i++) {
                    JSONObject x = a.optJSONObject(i);
                    try {
                        String job = x.optString("job").isEmpty() ? x.optString("id") : x.optString("job");
                        job = job.replaceAll("(?i)(\\.gcode)?\\.3mf$", "");
                        String id = x.optString("id");
                        String when = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(new java.util.Date(x.optLong("t") * 1000L));
                        JSONObject t = new JSONObject();
                        t.put("name", job + ".mp4");
                        t.put("size", x.optLong("bytes"));
                        t.put("date", when + " · " + x.optInt("frames") + " layers");
                        t.put("url", "/api/timelapse/" + q(id) + "/timelapse.mp4");
                        t.put("thumbUrl", "/api/timelapse/" + q(id) + "/thumb.jpg");
                        t.put("pi", id);
                        t.put("video", x.optBoolean("video"));
                        t.put("state", x.optBoolean("rendering") ? "Making video..." : x.optBoolean("queued") ? "Queued" : "");
                        busy |= x.optBoolean("rendering") || x.optBoolean("queued");
                        piList.addView(row(t));
                    } catch (Exception ignored) { }
                }
                if (busy) ui.postDelayed(new Runnable() { public void run() { if (!isFinishing()) loadPi(); } }, 4000);
            }
        });
    }

    private void load(boolean refresh) {
        loadPi();
        getJson("/api/timelapses" + (refresh ? "?refresh=1" : ""), new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                list.removeAllViews();
                if (e != null) { status.setText(e); return; }
                JSONArray a = v.optJSONArray("list");
                int n = a == null ? 0 : a.length();
                status.setText(n == 0 ? "No timelapses on the SD card yet." : n + " video" + (n == 1 ? "" : "s"));
                for (int i = 0; i < n; i++) list.addView(row(a.optJSONObject(i)));
            }
        });
    }

    private View row(final JSONObject t) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int p = Ui.dp(c, 10);
        r.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        ImageView th = thumb(96, 54);
        r.addView(th);
        if (t.has("thumbUrl")) image(t.optString("thumbUrl"), th);
        else if (!t.isNull("thumb")) image("/api/timelapses/thumb?path=" + q(t.optString("thumb")), th);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, 0, 0);
        TextView nm = Ui.text(c, t.optString("name"), 13, Ui.TEXT, true);
        nm.setSingleLine(true);
        info.addView(nm);
        boolean noVid = t.has("pi") && !t.optBoolean("video");
        String sub = noVid ? (t.optString("state").isEmpty() ? "Tap to make the video" : t.optString("state")) + " · " + t.optString("date")
                : size(t.optLong("size")) + " · " + t.optString("date");
        TextView s = Ui.text(c, sub, 12, noVid && t.optString("state").isEmpty() ? Ui.ACCENT : Ui.MUTED, false);
        s.setTypeface(Ui.MONO);
        info.addView(s);
        r.addView(info, Ui.weight(1));
        r.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                if (t.has("pi") && !t.optBoolean("video")) {
                    if (!t.optString("state").isEmpty()) return;
                    post("/api/timelapse/" + q(t.optString("pi")) + "/render", "{}", new Done<JSONObject>() {
                        public void run(JSONObject r, String e) { toast(e != null ? e : "Making the video..."); loadPi(); }
                    });
                    return;
                }
                new AlertDialog.Builder(TimelapseActivity.this, android.R.style.Theme_Material_Dialog_Alert)
                        .setTitle(t.optString("name"))
                        .setItems(new String[]{"Play", "Save / share"}, new DialogInterface.OnClickListener() {
                            public void onClick(DialogInterface d, int which) { fetch(t, which == 1); }
                        }).show();
            }
        });
        return r;
    }

    /** Download inside the app (works at home and away), then play or share it. */
    private void fetch(final JSONObject t, final boolean share) {
        final String name = t.optString("name").replaceAll("[^A-Za-z0-9._-]", "_");
        final java.io.File out = new java.io.File(VideoProvider.dir(this), name);
        if (out.exists() && out.length() == t.optLong("size")) { open(name, share); return; }
        final android.app.ProgressDialog pd = new android.app.ProgressDialog(this, android.R.style.Theme_Material_Dialog_Alert);
        pd.setTitle("Downloading");
        pd.setMessage(t.optString("name"));
        pd.setProgressStyle(android.app.ProgressDialog.STYLE_HORIZONTAL);
        pd.setMax(100);
        pd.setCancelable(true);
        final boolean[] cancelled = {false};
        pd.setOnCancelListener(new DialogInterface.OnCancelListener() {
            public void onCancel(DialogInterface d) { cancelled[0] = true; }
        });
        pd.show();
        net.execute(new Runnable() {
            public void run() {
                String err = null;
                java.net.HttpURLConnection h = null;
                java.io.File tmp = new java.io.File(out.getPath() + ".part");
                try {
                    h = Api.stream(TimelapseActivity.this, t.has("url") ? t.optString("url")
                            : "/api/timelapses/download?path=" + q(t.optString("path")));
                    if (h.getResponseCode() != 200) throw new java.io.IOException("HTTP " + h.getResponseCode());
                    long total = t.optLong("size"), got = 0;
                    java.io.InputStream in = h.getInputStream();
                    java.io.FileOutputStream fo = new java.io.FileOutputStream(tmp);
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        if (cancelled[0]) throw new java.io.IOException("cancelled");
                        fo.write(buf, 0, n);
                        got += n;
                        final int pct = total > 0 ? (int) (got * 100 / total) : 0;
                        ui.post(new Runnable() { public void run() { pd.setProgress(pct); } });
                    }
                    fo.close();
                    in.close();
                    if (!tmp.renameTo(out)) throw new java.io.IOException("couldn't save");
                } catch (Exception e) {
                    err = e.getMessage();
                    tmp.delete();
                } finally {
                    if (h != null) h.disconnect();
                }
                final String fe = err;
                ui.post(new Runnable() {
                    public void run() {
                        try { pd.dismiss(); } catch (Exception ignored) { }
                        if (fe != null) { if (!cancelled[0]) toast("Download failed: " + fe); return; }
                        open(name, share);
                    }
                });
            }
        });
    }

    private void open(String name, boolean share) {
        Uri u = VideoProvider.uri(name);
        Intent it;
        if (share) {
            it = new Intent(Intent.ACTION_SEND);
            it.setType(name.toLowerCase().endsWith(".mp4") ? "video/mp4" : "video/x-msvideo");
            it.putExtra(Intent.EXTRA_STREAM, u);
            it = Intent.createChooser(it, "Save or share timelapse");
        } else {
            it = new Intent(Intent.ACTION_VIEW);
            it.setDataAndType(u, name.toLowerCase().endsWith(".mp4") ? "video/mp4" : "video/x-msvideo");
        }
        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(it);
        } catch (ActivityNotFoundException e) {
            toast("No video player found. Install one (for example VLC) or use Save / share.");
        }
    }
}
