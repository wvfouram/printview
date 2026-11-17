package dev.printwatch;

import android.content.Context;
import android.os.Bundle;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;

/** Every finished print with its final photo, plus the last 7 days summary. */
public class HistoryActivity extends Base {
    private LinearLayout list;
    private TextView report;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Print history");
        report = note(p, "Loading...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        getJson("/api/report", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) { report.setText(e); return; }
                JSONArray l = v.optJSONArray("lines");
                StringBuilder sb = new StringBuilder("Last 7 days\n");
                for (int i = 0; l != null && i < l.length(); i++) sb.append(l.optString(i)).append('\n');
                report.setText(sb.toString().trim());
            }
        });
        getJson("/api/spools", new Done<JSONObject>() {
            public void run(JSONObject v, String e) { if (v != null) cur = v.optString("currency", "$"); }
        });
        getJson("/api/history", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) return;
                JSONArray a = v.optJSONArray("items");
                if (a == null || a.length() == 0) { list.addView(Ui.text(HistoryActivity.this, "Prints show up here when they finish.", 13, Ui.MUTED, false)); return; }
                for (int i = 0; i < a.length(); i++) list.addView(row(a.optJSONObject(i)));
            }
        });
    }

    private LinearLayout row(JSONObject x) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int pd = Ui.dp(c, 10);
        r.setPadding(pd, pd, pd, pd);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        ImageView th = thumb(96, 54);
        r.addView(th);
        if (!x.isNull("photo")) image("/api/history/photo/" + x.optString("photo"), th);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, 0, 0);
        info.addView(Ui.text(c, x.optString("job"), 15, Ui.TEXT, true));
        String when = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(new Date(x.optLong("end") * 1000L));
        info.addView(Ui.text(c, when + " · " + Ui.mins(x.optDouble("minutes")), 12, Ui.MUTED, false));
        boolean ok = "done".equals(x.optString("result"));
        info.addView(Ui.text(c, ok ? "Finished" : "Failed at " + x.optInt("percent") + "%" + (x.isNull("cause") || x.optString("cause").isEmpty() ? "" : ": " + x.optString("cause")),
                12, ok ? Ui.OK : Ui.DANGER, false));
        if (x.optDouble("grams", 0) > 0) {
            String cost = x.isNull("cost") || !x.has("cost") ? "" : " · " + cur + String.format(java.util.Locale.US, "%.2f", x.optDouble("cost"));
            info.addView(Ui.text(c, Math.round(x.optDouble("grams")) + " g · " + x.optDouble("meters") + " m" + cost, 12, Ui.MUTED, false));
        }
        if (ok && x.optInt("est_minutes") > 0)
            info.addView(Ui.text(c, "Estimated " + Ui.mins(x.optDouble("est_minutes")) + ", took " + Ui.mins(x.optDouble("print_minutes", x.optDouble("minutes")))
                    + (x.optInt("paused_minutes") > 0 ? " (+" + Ui.mins(x.optDouble("paused_minutes")) + " paused)" : ""), 12, Ui.MUTED, false));
        final TextView stars = Ui.text(c, starText(x.optInt("stars")), 18, Ui.ACCENT, false);
        stars.setPadding(0, Ui.dp(c, 6), 0, 0);
        info.addView(stars);
        final TextView nt = Ui.text(c, x.optString("note", "").isEmpty() ? "Tap to rate or add a note" : x.optString("note"), 12.5f,
                x.optString("note", "").isEmpty() ? Ui.FAINT : Ui.TEXT, false);
        nt.setPadding(0, Ui.dp(c, 4), 0, 0);
        info.addView(nt);
        final String hid = x.optString("id");
        final JSONObject fx = x;
        r.setOnClickListener(new android.view.View.OnClickListener() { public void onClick(android.view.View v) { edit(hid, fx, stars, nt); } });
        r.addView(info, Ui.weight(1));
        return r;
    }

    private String cur = "$";

    private static String starText(int n) {
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= 5; i++) sb.append(i <= n ? "\u2605" : "\u2606");
        return sb.toString();
    }

    /** Rate 1-5 stars and write a note (like: warped corner, use a brim next time). */
    private void edit(final String hid, final JSONObject x, final TextView stars, final TextView nt) {
        Context c = this;
        LinearLayout v = new LinearLayout(c);
        v.setOrientation(LinearLayout.VERTICAL);
        int pd = Ui.dp(c, 18);
        v.setPadding(pd, Ui.dp(c, 8), pd, 0);
        final int[] pick = {x.optInt("stars")};
        LinearLayout sr = Ui.row(c);
        final TextView[] st = new TextView[5];
        for (int i = 0; i < 5; i++) {
            final int n = i + 1;
            st[i] = Ui.text(c, n <= pick[0] ? "\u2605" : "\u2606", 30, Ui.ACCENT, false);
            st[i].setPadding(0, 0, Ui.dp(c, 10), 0);
            st[i].setOnClickListener(new android.view.View.OnClickListener() { public void onClick(android.view.View b) {
                pick[0] = n;
                for (int k = 0; k < 5; k++) st[k].setText(k < n ? "\u2605" : "\u2606");
            } });
            sr.addView(st[i]);
        }
        v.addView(sr);
        final android.widget.EditText e = new android.widget.EditText(c);
        e.setText(x.optString("note", ""));
        e.setHint("Note, like: warped corner, use a brim next time");
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(Ui.FAINT);
        v.addView(e);
        new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(x.optString("job")).setView(v).setNegativeButton("Cancel", null)
                .setPositiveButton("Save", new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int w) {
                        final String note = e.getText().toString();
                        post("/api/history/" + hid + "/note", "{\"note\":" + JSONObject.quote(note) + (pick[0] > 0 ? ",\"stars\":" + pick[0] : "") + "}",
                                new Done<JSONObject>() { public void run(JSONObject r, String err) {
                                    if (err != null) { toast(err); return; }
                                    try { x.put("note", note); x.put("stars", pick[0]); } catch (Exception ignored) { }
                                    stars.setText(starText(pick[0]));
                                    nt.setText(note.isEmpty() ? "Tap to rate or add a note" : note);
                                    nt.setTextColor(note.isEmpty() ? Ui.FAINT : Ui.TEXT);
                                    toast("Saved");
                                } });
                    }
                }).show();
    }
}
