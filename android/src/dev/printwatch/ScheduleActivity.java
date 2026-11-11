package dev.printwatch;

import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;

/** Everything scheduled: waiting ones with a countdown and Cancel, plus recent started / failed ones. */
public class ScheduleActivity extends Base {
    private LinearLayout list;
    private TextView msg;
    private final Runnable tick = new Runnable() { public void run() { load(); ui.postDelayed(this, 30000); } };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Scheduled prints");
        msg = note(p, "Loading...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        note(p, "To schedule a print, open a file in Files and tap \"Schedule for later\".");
    }

    @Override protected void onResume() { super.onResume(); ui.post(tick); }
    @Override protected void onPause() { super.onPause(); ui.removeCallbacks(tick); }

    private void load() {
        getJson("/api/schedule", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) { msg.setText(e); return; }
                JSONArray a = v.optJSONArray("items");
                list.removeAllViews();
                int waiting = 0;
                long now = System.currentTimeMillis() / 1000;
                for (int i = 0; a != null && i < a.length(); i++) {
                    JSONObject x = a.optJSONObject(i);
                    if ("waiting".equals(x.optString("status"))) waiting++;
                }
                msg.setText(waiting == 0 ? "Nothing waiting to print." : waiting + " waiting to print");
                // waiting first (soonest on top), then the rest (newest on top)
                for (int pass = 0; pass < 2 && a != null; pass++) {
                    java.util.List<JSONObject> l = new java.util.ArrayList<>();
                    for (int i = 0; i < a.length(); i++) {
                        JSONObject x = a.optJSONObject(i);
                        if ("waiting".equals(x.optString("status")) == (pass == 0)) l.add(x);
                    }
                    if (pass == 0) java.util.Collections.reverse(l);
                    for (JSONObject x : l) list.addView(row(x, now));
                }
            }
        });
    }

    private View row(final JSONObject x, long now) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int pd = Ui.dp(c, 12);
        r.setPadding(pd, pd, pd, pd);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        String st = x.optString("status");
        long at = (long) x.optDouble("at");
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        TextView name = Ui.text(c, x.optString("name").replaceAll("(?i)(\\.gcode)?\\.3mf$", ""), 15, Ui.TEXT, true);
        name.setSingleLine(true);
        name.setEllipsize(android.text.TextUtils.TruncateAt.END);
        info.addView(name);
        String when = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(new Date(at * 1000L));
        info.addView(Ui.text(c, when + (x.optString("msg").isEmpty() ? "" : " · " + x.optString("msg")), 12, Ui.MUTED, false));
        if ("waiting".equals(st)) {
            long s = Math.max(0, at - now);
            info.addView(Ui.text(c, s < 60 ? "Starting now" : "in " + Ui.mins(s / 60.0), 13, Ui.ACCENT, true));
        } else {
            int col = "started".equals(st) ? Ui.OK : "cancelled".equals(st) ? Ui.MUTED : Ui.DANGER;
            info.addView(Ui.text(c, st.substring(0, 1).toUpperCase() + st.substring(1), 12, col, false));
        }
        r.addView(info, Ui.weight(1));
        if ("waiting".equals(st)) {
            Button cx = Ui.button(c, "Cancel", Ui.alpha(Ui.DANGER, 0.15f), Ui.DANGER, 0);
            cx.setTextSize(13);
            cx.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    confirm("Cancel this print?", x.optString("name"), "Cancel print", new Runnable() {
                        public void run() {
                            post("/api/schedule/" + x.optString("id") + "/cancel", "{}", new Done<JSONObject>() {
                                public void run(JSONObject v2, String e) { toast(e != null ? e : "Cancelled"); load(); }
                            });
                        }
                    });
                }
            });
            r.addView(cx);
        }
        return r;
    }
}
