package dev.printwatch;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ForegroundColorSpan;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;

/**
 * Live data streams: Arduino <-> Pi (bed relay serial), Pi <-> P1S (MQTT), web/phone <-> Pi (HTTP).
 * Polls /api/streams every second and shows the newest lines of each.
 */
public class StreamActivity extends Base {
    private static final String[] KEYS = {"uno", "p1s", "web"};
    private static final String[] TITLES = {"Arduino  ⇄  Pi", "Pi  ⇄  P1S", "Web / phone  ⇄  Pi"};
    private static final int SHOW = 40;

    private final TextView[] views = new TextView[3];
    private final TextView[] counts = new TextView[3];
    @SuppressWarnings("unchecked")
    private final ArrayList<String>[] lines = new ArrayList[3];
    private final boolean[] shown = {true, true, true};
    private long seq = 0;
    private boolean running, paused;
    private TextView err;
    private Button pauseBtn;
    private final SimpleDateFormat hms = new SimpleDateFormat("HH:mm:ss", Locale.US);

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Context c = this;
        LinearLayout r = page("Back", "Data streams");

        TextView intro = Ui.text(c, "Live traffic, newest at the bottom. Green = into the Pi, amber = out of the Pi.", 13, Ui.MUTED, false);
        intro.setPadding(0, Ui.dp(c, 10), 0, 0);
        r.addView(intro);

        err = Ui.text(c, "", 13.5f, Color.parseColor("#ffd7d4"), false);
        err.setBackground(Ui.box(c, Color.parseColor("#2b1514"), 0, 16));
        err.setPadding(Ui.dp(c, 16), Ui.dp(c, 12), Ui.dp(c, 16), Ui.dp(c, 12));
        err.setVisibility(View.GONE);
        LinearLayout.LayoutParams el = new LinearLayout.LayoutParams(-1, -2);
        el.topMargin = Ui.dp(c, 12);
        r.addView(err, el);

        LinearLayout btns = Ui.row(c);
        pauseBtn = Ui.button(c, "Pause", Ui.SURFACE2, Ui.TEXT, 0);
        pauseBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { paused = !paused; pauseBtn.setText(paused ? "Resume" : "Pause"); }
        });
        Button clear = Ui.button(c, "Clear", Ui.SURFACE2, Ui.TEXT, 0);
        clear.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { for (int i = 0; i < 3; i++) { lines[i].clear(); paint(i); } }
        });
        btns.addView(pauseBtn, Ui.weight(1));
        View gap = new View(c);
        btns.addView(gap, new LinearLayout.LayoutParams(Ui.dp(c, 10), 1));
        btns.addView(clear, Ui.weight(1));
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-1, -2);
        bl.topMargin = Ui.dp(c, 12);
        r.addView(btns, bl);

        for (int i = 0; i < 3; i++) {
            lines[i] = new ArrayList<String>();
            final int k = i;
            LinearLayout card = Ui.card(c);
            LinearLayout head = Ui.row(c);
            TextView t = Ui.text(c, TITLES[i], 15, Ui.TEXT, true);
            head.addView(t, Ui.weight(1));
            counts[i] = Ui.text(c, "", 12, Ui.MUTED, false);
            head.addView(counts[i]);
            card.addView(head);
            head.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { shown[k] = !shown[k]; views[k].setVisibility(shown[k] ? View.VISIBLE : View.GONE); }
            });
            views[i] = Ui.text(c, "Waiting for data...", 11, Ui.MUTED, false);
            views[i].setTypeface(Typeface.MONOSPACE);
            views[i].setTextIsSelectable(true);
            LinearLayout.LayoutParams vl = new LinearLayout.LayoutParams(-1, -2);
            vl.topMargin = Ui.dp(c, 8);
            card.addView(views[i], vl);
            LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-1, -2);
            cl.topMargin = Ui.dp(c, 12);
            r.addView(card, cl);
        }
    }

    @Override
    protected void onResume() { super.onResume(); running = true; tick(); }

    @Override
    protected void onPause() { super.onPause(); running = false; }

    private void tick() {
        if (!running) return;
        if (!paused) load();
        ui.postDelayed(new Runnable() { public void run() { tick(); } }, 1000);
    }

    private void load() {
        getJson("/api/streams?since=" + seq, new Done<JSONObject>() {
            public void run(JSONObject s, String e) {
                if (e != null || s == null) {
                    err.setText(e == null ? "No answer from the Pi" : e + (e.contains("404") ? " (update the Pi first)" : ""));
                    err.setVisibility(View.VISIBLE);
                    return;
                }
                err.setVisibility(View.GONE);
                long ns = s.optLong("seq", seq);
                if (ns < seq) { for (int i = 0; i < 3; i++) lines[i].clear(); }   // Pi restarted
                seq = ns;
                JSONObject st = s.optJSONObject("streams");
                if (st == null) return;
                for (int i = 0; i < 3; i++) {
                    JSONArray a = st.optJSONArray(KEYS[i]);
                    if (a == null || a.length() == 0) continue;
                    for (int j = 0; j < a.length(); j++) {
                        JSONObject o = a.optJSONObject(j);
                        if (o == null) continue;
                        lines[i].add(hms.format(new Date((long) (o.optDouble("t") * 1000))) + " " + o.optString("s"));
                    }
                    while (lines[i].size() > SHOW) lines[i].remove(0);
                    paint(i);
                }
            }
        });
    }

    private void paint(int i) {
        if (lines[i].isEmpty()) { views[i].setText("Nothing yet"); counts[i].setText(""); return; }
        SpannableStringBuilder sb = new SpannableStringBuilder();
        for (String l : lines[i]) {
            int start = sb.length();
            sb.append(l).append('\n');
            int col = l.contains("> Pi") ? Ui.OK : l.contains("Pi >") ? Ui.ACCENT : Ui.MUTED;
            if (l.contains("FAULT") || l.contains("-> 5") || l.contains("-> 4")) col = Ui.DANGER;
            sb.setSpan(new ForegroundColorSpan(col), start, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        views[i].setText(sb);
        counts[i].setText(lines[i].size() + " lines");
    }
}
