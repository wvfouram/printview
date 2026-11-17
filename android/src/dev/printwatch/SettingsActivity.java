package dev.printwatch;

import android.content.Context;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONObject;

import java.util.Locale;

/** Printer name, quiet hours, after a print, spaghetti first-layer grace, timelapse look, Pi fan. */
public class SettingsActivity extends Base {
    private LinearLayout box, fanBox;
    private boolean filling;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Settings");
        box = Ui.card(this);
        p.addView(box);
        fanBox = Ui.card(this);
        p.addView(fanBox);
        load();
    }

    private void save(String json) {
        if (filling) return;
        post("/api/settings", json, new Done<JSONObject>() {
            public void run(JSONObject v, String e) { toast(e == null ? "Saved" : e); }
        });
    }

    private Switch sw(String title, String sub, boolean on, final String key) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 12), 0, 0);
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        t.addView(Ui.text(c, title, 15, Ui.TEXT, true));
        if (sub != null) t.addView(Ui.text(c, sub, 12, Ui.MUTED, false));
        r.addView(t, Ui.weight(1));
        Switch s = new Switch(c);
        s.setChecked(on);
        s.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton bt, boolean v) { save("{\"" + key + "\":" + v + "}"); }
        });
        r.addView(s);
        box.addView(r);
        return s;
    }

    private EditText field(String text, String hint) {
        EditText e = new EditText(this);
        e.setText(text);
        e.setHint(hint);
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(Ui.FAINT);
        e.setSingleLine(true);
        e.setTextSize(14);
        e.setBackground(Ui.box(this, Ui.SURFACE2, Ui.LINE, 10));
        int pd = Ui.dp(this, 10);
        e.setPadding(pd, pd, pd, pd);
        return e;
    }

    /** A row of choice buttons; the one matching cur is highlighted. */
    private void choices(String title, String sub, final String[] labels, final String[] values, String cur, final String key, final boolean quote) {
        Context c = this;
        box.addView(Ui.space(c, 12));
        box.addView(Ui.text(c, title, 15, Ui.TEXT, true));
        if (sub != null) box.addView(Ui.text(c, sub, 12, Ui.MUTED, false));
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 6), 0, 0);
        final Button[] bs = new Button[labels.length];
        for (int i = 0; i < labels.length; i++) {
            final int k = i;
            boolean on = values[i].equals(cur);
            bs[i] = Ui.button(c, labels[i], on ? Ui.ACCENT : Ui.SURFACE2, on ? 0xff1a1206 : Ui.TEXT, on ? 0 : Ui.LINE);
            bs[i].setTextSize(12.5f);
            bs[i].setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
                for (int j = 0; j < bs.length; j++) {
                    bs[j].setBackground(Ui.box(SettingsActivity.this, j == k ? Ui.ACCENT : Ui.SURFACE2, j == k ? 0 : Ui.LINE, 12));
                    bs[j].setTextColor(j == k ? 0xff1a1206 : Ui.TEXT);
                }
                save("{\"" + key + "\":" + (quote ? JSONObject.quote(values[k]) : values[k]) + "}");
            } });
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 4);
            r.addView(bs[i], lp);
        }
        box.addView(r);
    }

    private void load() {
        getJson("/api/status", new Done<JSONObject>() {
            public void run(JSONObject s, String e) {
                if (e != null) { note(box, e); return; }
                filling = true;
                fill(s.optJSONObject("settings") == null ? new JSONObject() : s.optJSONObject("settings"));
                fan(s.optJSONObject("pifan"));
                filling = false;
            }
        });
    }

    private void fill(JSONObject st) {
        Context c = this;
        box.removeAllViews();
        box.addView(Ui.heading(c, "Settings"));
        box.addView(Ui.space(c, 10));
        box.addView(Ui.text(c, "Printer name", 15, Ui.TEXT, true));
        box.addView(Ui.text(c, "Shown at the top of the app and website, and in alerts", 12, Ui.MUTED, false));
        LinearLayout nr = Ui.row(c);
        nr.setPadding(0, Ui.dp(c, 6), 0, 0);
        final EditText name = field(st.optString("printer_name", ""), "PrintView");
        nr.addView(name, Ui.weight(1));
        Button ns = Ui.button(c, "Save", Ui.ACCENT, 0xff1a1206, 0);
        ns.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { save("{\"printer_name\":" + JSONObject.quote(name.getText().toString()) + "}"); } });
        nr.addView(ns);
        box.addView(nr);

        sw("Quiet hours", "A running print switches to Silent speed during these hours, and back after", st.optBoolean("quiet_on"), "quiet_on");
        LinearLayout qr = Ui.row(c);
        qr.setPadding(0, Ui.dp(c, 6), 0, 0);
        qr.addView(Ui.text(c, "From ", 13, Ui.MUTED, false));
        final EditText qs = field(st.optString("quiet_start", "22:00"), "22:00");
        qr.addView(qs, Ui.weight(1));
        qr.addView(Ui.text(c, "  to  ", 13, Ui.MUTED, false));
        final EditText qe = field(st.optString("quiet_end", "07:00"), "07:00");
        qr.addView(qe, Ui.weight(1));
        Button qb = Ui.button(c, "Save", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        qb.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            save("{\"quiet_start\":" + JSONObject.quote(qs.getText().toString().trim()) + ",\"quiet_end\":" + JSONObject.quote(qe.getText().toString().trim()) + "}");
        } });
        LinearLayout.LayoutParams ql = new LinearLayout.LayoutParams(-2, -2);
        ql.leftMargin = Ui.dp(c, 6);
        qr.addView(qb, ql);
        box.addView(qr);
        box.addView(Ui.text(c, "24-hour time, like 22:00 for 10 PM.", 12, Ui.FAINT, false));
        sw("Also turn the chamber light off", "The camera can't see in the dark, so spaghetti detection can't work while it's off", st.optBoolean("quiet_light"), "quiet_light");

        sw("Heaters off after a print", "Makes sure the nozzle and bed are off when a print ends", st.optBoolean("finish_cooldown", true), "finish_cooldown");
        choices("Light off after a print", "Waits at least 3 minutes so the finish photos are taken",
                new String[]{"Never", "3 min", "10 min", "30 min", "1 h"}, new String[]{"0", "3", "10", "30", "60"},
                String.valueOf(st.optInt("finish_light_off_min", 10)), "finish_light_off_min", false);
        choices("Spaghetti watch: ignore the first layers", "The bed and first lines can look like spaghetti",
                new String[]{"Off", "1", "2", "3", "5"}, new String[]{"0", "1", "2", "3", "5"},
                String.valueOf(st.optInt("first_layer_grace", 2)), "first_layer_grace", false);
        sw("Check the plate before Start next", "Looks at the bed and asks before starting if something may be on it", st.optBoolean("plate_check_next", true), "plate_check_next");
        sw("Name and progress bar on timelapses", "For new timelapse videos and Redo", st.optBoolean("tl_overlay", true), "tl_overlay");
        sw("Show print stats to everyone", "The small stats on the website's status card", st.optBoolean("public_stats", true), "public_stats");
    }

    private void fan(JSONObject f) {
        Context c = this;
        fanBox.removeAllViews();
        fanBox.addView(Ui.heading(c, "Pi fan"));
        if (f == null) return;
        TextView info = Ui.text(c, !f.optBoolean("helper") ? "The fan helper isn't running on the Pi. Run the update command to install it."
                : "Pi CPU " + (f.isNull("temp") ? "--" : String.format(Locale.US, "%.1f°C", f.optDouble("temp")))
                + (f.isNull("now_pct") ? "" : "  ·  fan " + f.optInt("now_pct") + "%") + (f.isNull("rpm") ? "" : "  ·  " + f.optInt("rpm") + " rpm")
                + (f.optBoolean("safety") ? "  ·  too hot, running full speed" : ""), 13, Ui.MUTED, false);
        info.setPadding(0, Ui.dp(c, 6), 0, Ui.dp(c, 6));
        fanBox.addView(info);
        final String[] labels = {"Auto", "Quiet", "Cool", "Max"};
        final String[] modes = {"auto", "quiet", "cool", "max"};
        LinearLayout r = Ui.row(c);
        for (int i = 0; i < modes.length; i++) {
            final String m = modes[i];
            boolean on = m.equals(f.optString("mode"));
            Button b = Ui.button(c, labels[i], on ? Ui.ACCENT : Ui.SURFACE2, on ? 0xff1a1206 : Ui.TEXT, on ? 0 : Ui.LINE);
            b.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
                post("/api/pifan", "{\"mode\":\"" + m + "\"}", new Done<JSONObject>() {
                    public void run(JSONObject x, String e) { toast(e == null ? "Fan: " + m : e); if (e == null) load(); }
                });
            } });
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 4);
            r.addView(b, lp);
        }
        fanBox.addView(r);
        fanBox.addView(Ui.text(c, "Auto is the Pi's own curve. Quiet stays off until 60°C. Cool keeps at least 40%. At 75°C it always runs full speed.", 12, Ui.FAINT, false));
    }
}
