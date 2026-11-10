package dev.printwatch;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/** Sliced files on the printer's SD card. Tap one to print it. */
public class FilesActivity extends Base {
    private LinearLayout list;
    private TextView status;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Live", "Print from SD card");
        Button refresh = Ui.button(this, "Refresh", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        refresh.setTextSize(14);
        refresh.setMinHeight(Ui.dp(this, 44));
        refresh.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { load(true); } });
        p.addView(refresh);
        Button up = Ui.button(this, "Upload a print file", Ui.ACCENT, Ui.BG, 0);
        up.setTextSize(14);
        up.setMinHeight(Ui.dp(this, 44));
        up.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                Intent it = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                it.addCategory(Intent.CATEGORY_OPENABLE);
                it.setType("*/*");
                startActivityForResult(it, 41);
            }
        });
        LinearLayout.LayoutParams ul = new LinearLayout.LayoutParams(-1, -2);
        ul.topMargin = Ui.dp(this, 8);
        p.addView(up, ul);
        status = note(p, "Reading the SD card...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        note(p, "Upload a sliced .gcode.3mf from your phone (works away from home too), or send from Bambu Studio / OrcaSlicer at home. New files appear at the top. Press and hold a file to download or delete it.");
        load(false);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == 42 && res == RESULT_OK && data != null && data.getData() != null && pending != null) {
            download(data.getData(), pending);
            return;
        }
        if (req != 41 || res != RESULT_OK || data == null || data.getData() == null) return;
        final android.net.Uri uri = data.getData();
        String name = "upload.gcode.3mf";
        long size = -1;
        android.database.Cursor cu = getContentResolver().query(uri, null, null, null, null);
        if (cu != null) {
            if (cu.moveToFirst()) {
                int ni = cu.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME);
                int si = cu.getColumnIndex(android.provider.OpenableColumns.SIZE);
                if (ni >= 0) name = cu.getString(ni);
                if (si >= 0 && !cu.isNull(si)) size = cu.getLong(si);
            }
            cu.close();
        }
        if (!name.toLowerCase(java.util.Locale.US).matches(".*\\.(3mf|gcode)$")) {
            status.setText("Pick a .gcode.3mf, .3mf or .gcode file");
            return;
        }
        final String fname = name;
        final long fsize = size;
        status.setText("Uploading " + fname + "...");
        new Thread(new Runnable() {
            public void run() {
                String msg;
                java.net.HttpURLConnection h = null;
                try {
                    h = Api.stream(FilesActivity.this, "/api/upload?name=" + java.net.URLEncoder.encode(fname, "UTF-8"));
                    h.setReadTimeout(300000);
                    h.setDoOutput(true);
                    h.setRequestMethod("POST");
                    h.setRequestProperty("Content-Type", "application/octet-stream");
                    if (fsize > 0) h.setFixedLengthStreamingMode(fsize); else h.setChunkedStreamingMode(65536);
                    java.io.InputStream in = getContentResolver().openInputStream(uri);
                    java.io.OutputStream out = h.getOutputStream();
                    byte[] buf = new byte[65536];
                    long sent = 0, last = 0;
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                        sent += n;
                        if (fsize > 0 && System.currentTimeMillis() - last > 300) {
                            last = System.currentTimeMillis();
                            final int pc = (int) (sent * 100 / fsize);
                            ui.post(new Runnable() { public void run() { status.setText("Uploading " + fname + " - " + pc + "%"); } });
                        }
                    }
                    in.close();
                    out.close();
                    int code = h.getResponseCode();
                    java.io.InputStream rs = code >= 400 ? h.getErrorStream() : h.getInputStream();
                    String body = "";
                    if (rs != null) {
                        java.util.Scanner sc = new java.util.Scanner(rs, "UTF-8").useDelimiter("\\A");
                        body = sc.hasNext() ? sc.next() : "";
                        rs.close();
                    }
                    JSONObject j = body.isEmpty() ? new JSONObject() : new JSONObject(body);
                    msg = code == 200 && j.optBoolean("ok") ? "Uploaded " + j.optString("name") + " - it's at the top of the list"
                            : "Upload failed: " + j.optString("error", "HTTP " + code);
                } catch (Exception e) {
                    msg = "Upload failed: " + e.getMessage();
                } finally {
                    if (h != null) h.disconnect();
                }
                final String m = msg;
                ui.post(new Runnable() { public void run() { if (!isFinishing()) { android.widget.Toast.makeText(FilesActivity.this, m, android.widget.Toast.LENGTH_LONG).show(); load(true); } } });
            }
        }).start();
    }

    private void load(boolean refresh) {
        status.setText("Reading the SD card...");
        getJson("/api/files" + (refresh ? "?refresh=1" : ""), new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                list.removeAllViews();
                if (e != null) { status.setText(e); return; }
                JSONArray a = v.optJSONArray("list");
                int n = a == null ? 0 : a.length();
                status.setText(n == 0 ? "No sliced .3mf files on the SD card." : n + " file" + (n == 1 ? "" : "s"));
                for (int i = 0; i < n; i++) list.addView(row(a.optJSONObject(i)));
            }
        });
    }

    private View row(final JSONObject f) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int p = Ui.dp(c, 10);
        r.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        ImageView th = thumb(64, 64);
        r.addView(th);
        image("/api/files/plate.png?plate=1&path=" + q(f.optString("path")), th);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, 0, 0);
        TextView t = Ui.text(c, f.optString("title"), 15, Ui.TEXT, true);
        t.setSingleLine(true);
        info.addView(t);
        TextView s = Ui.text(c, f.optString("path") + "\n" + size(f.optLong("size")) + " · " + f.optString("date"), 12, Ui.MUTED, false);
        s.setTypeface(Ui.MONO);
        info.addView(s);
        r.addView(info, Ui.weight(1));
        r.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                Intent it = new Intent(FilesActivity.this, StartActivity.class);
                it.putExtra("path", f.optString("path"));
                it.putExtra("title", f.optString("title"));
                startActivity(it);
            }
        });
        r.setOnLongClickListener(new View.OnLongClickListener() {
            public boolean onLongClick(View v) { fileMenu(f); return true; }
        });
        return r;
    }

    private JSONObject pending;

    private void fileMenu(final JSONObject f) {
        new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(f.optString("title"))
                .setItems(new String[]{"Download to phone", "Delete from SD card"}, new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int which) {
                        if (which == 0) {
                            pending = f;
                            Intent it = new Intent(Intent.ACTION_CREATE_DOCUMENT);
                            it.addCategory(Intent.CATEGORY_OPENABLE);
                            it.setType("application/octet-stream");
                            it.putExtra(Intent.EXTRA_TITLE, f.optString("name", f.optString("title") + ".gcode.3mf"));
                            startActivityForResult(it, 42);
                        } else {
                            new android.app.AlertDialog.Builder(FilesActivity.this, android.R.style.Theme_Material_Dialog_Alert)
                                    .setTitle("Delete " + f.optString("title") + "?")
                                    .setMessage("It's removed from the printer's SD card. This can't be undone.")
                                    .setNegativeButton("Cancel", null)
                                    .setPositiveButton("Delete", new android.content.DialogInterface.OnClickListener() {
                                        public void onClick(android.content.DialogInterface d2, int w) {
                                            status.setText("Deleting...");
                                            post("/api/files/delete", "{\"path\":" + JSONObject.quote(f.optString("path")) + "}", new Done<JSONObject>() {
                                                public void run(JSONObject v, String e) {
                                                    android.widget.Toast.makeText(FilesActivity.this, e == null ? "Deleted" : e, android.widget.Toast.LENGTH_LONG).show();
                                                    load(true);
                                                }
                                            });
                                        }
                                    }).show();
                        }
                    }
                }).show();
    }

    private void download(final android.net.Uri dest, final JSONObject f) {
        status.setText("Downloading " + f.optString("title") + "...");
        new Thread(new Runnable() {
            public void run() {
                String msg;
                java.net.HttpURLConnection h = null;
                try {
                    h = Api.stream(FilesActivity.this, "/api/files/download?path=" + java.net.URLEncoder.encode(f.optString("path"), "UTF-8"));
                    h.setReadTimeout(300000);
                    int code = h.getResponseCode();
                    if (code != 200) throw new java.io.IOException("HTTP " + code);
                    long total = h.getContentLength(), got = 0, last = 0;
                    java.io.InputStream in = h.getInputStream();
                    java.io.OutputStream out = getContentResolver().openOutputStream(dest);
                    byte[] buf = new byte[65536];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                        got += n;
                        if (total > 0 && System.currentTimeMillis() - last > 300) {
                            last = System.currentTimeMillis();
                            final int pc = (int) (got * 100 / total);
                            ui.post(new Runnable() { public void run() { status.setText("Downloading - " + pc + "%"); } });
                        }
                    }
                    out.close();
                    in.close();
                    msg = "Saved " + f.optString("title");
                } catch (Exception e) {
                    msg = "Download failed: " + e.getMessage();
                } finally {
                    if (h != null) h.disconnect();
                }
                final String m = msg;
                ui.post(new Runnable() { public void run() { if (!isFinishing()) { android.widget.Toast.makeText(FilesActivity.this, m, android.widget.Toast.LENGTH_LONG).show(); load(false); } } });
            }
        }).start();
    }
}
