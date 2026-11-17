package dev.printwatch;

import android.content.Context;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Iterator;
import java.util.Locale;

/** Success rate, hours, filament, cost, by month, most printed, why prints failed, estimate vs real. */
public class StatsActivity extends Base {
    private LinearLayout body;
    private final Button[] seg = new Button[3];
    private static final int[] DAYS = {30, 365, 0};
    private int days = 0;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Stats");
        Context c = this;
        LinearLayout r = Ui.row(c);
        String[] names = {"30 days", "This year", "All time"};
        for (int i = 0; i < 3; i++) {
            final int k = i;
            seg[i] = Ui.button(c, names[i], Ui.SURFACE2, Ui.TEXT, Ui.LINE);
            seg[i].setOnClickListener(new View.OnClickListener() { public void onClick(View v) { days = DAYS[k]; paint(); load(); } });
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 6);
            r.addView(seg[i], lp);
        }
        p.addView(r);
        body = new LinearLayout(c);
        body.setOrientation(LinearLayout.VERTICAL);
        p.addView(body);
        paint();
        load();
    }

    private void paint() {
        for (int i = 0; i < 3; i++) {
            boolean on = DAYS[i] == days;
            seg[i].setBackground(Ui.box(this, on ? Ui.ACCENT : Ui.SURFACE2, on ? 0 : Ui.LINE, 12));
            seg[i].setTextColor(on ? 0xff1a1206 : Ui.TEXT);
        }
    }

    private static String kg(double g) {
        return g >= 1000 ? String.format(Locale.US, "%.2f kg", g / 1000) : Math.round(g) + " g";
    }

    private void line(LinearLayout card, String left, String right) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 5), 0, Ui.dp(c, 5));
        TextView l = Ui.text(c, left, 14, Ui.TEXT, false);
        r.addView(l, Ui.weight(1));
        TextView v = Ui.text(c, right, 14, Ui.TEXT, true);
        v.setPadding(Ui.dp(c, 10), 0, 0, 0);
        r.addView(v);
        card.addView(r);
    }

    private LinearLayout section(String title) {
        LinearLayout card = Ui.card(this);
        TextView h = Ui.heading(this, title);
        h.setPadding(0, 0, 0, Ui.dp(this, 8));
        card.addView(h);
        body.addView(card);
        return card;
    }

    private void load() {
        body.removeAllViews();
        final TextView wait = note(body, "Loading...");
        getJson("/api/stats?days=" + days, new Done<JSONObject>() {
            public void run(JSONObject j, String e) {
                body.removeAllViews();
                if (e != null) { note(body, e); return; }
                if (j.optInt("prints") == 0) { note(body, "No prints in this time yet. Stats fill in as prints finish."); return; }
                String cur = j.optString("currency", "$");
                LinearLayout t = section("Totals");
                line(t, "Prints", j.optInt("prints") + "  (" + j.optInt("done") + " done, " + j.optInt("failed") + " failed)");
                line(t, "Success rate", j.optInt("success_pct") + "%");
                line(t, "Hours printed", String.valueOf(j.optDouble("hours")));
                line(t, "Filament", kg(j.optDouble("grams")) + "  ·  " + j.optDouble("meters") + " m");
                line(t, "Cost", j.isNull("cost") ? "-" : cur + String.format(Locale.US, "%.2f", j.optDouble("cost")));

                JSONArray ms = j.optJSONArray("months");
                if (ms != null && ms.length() > 0) {
                    LinearLayout m = section("By month");
                    for (int i = 0; i < ms.length(); i++) {
                        JSONObject x = ms.optJSONObject(i);
                        int pr = x.optInt("prints");
                        line(m, x.optString("month"), pr + " prints · " + (pr > 0 ? Math.round(x.optInt("done") * 100.0 / pr) : 0) + "% · "
                                + x.optDouble("hours") + " h · " + kg(x.optDouble("grams")) + (x.optDouble("cost") > 0 ? " · " + cur + String.format(Locale.US, "%.2f", x.optDouble("cost")) : ""));
                    }
                }
                JSONArray tf = j.optJSONArray("top_files");
                if (tf != null && tf.length() > 0) {
                    LinearLayout m = section("Most printed");
                    for (int i = 0; i < tf.length(); i++) {
                        JSONObject x = tf.optJSONObject(i);
                        line(m, x.optString("job"), x.optInt("prints") + "x · " + Math.round(x.optInt("done") * 100.0 / Math.max(1, x.optInt("prints"))) + "%");
                    }
                }
                JSONArray fc = j.optJSONArray("fail_causes");
                if (fc != null && fc.length() > 0) {
                    LinearLayout m = section("Why prints failed");
                    for (int i = 0; i < fc.length(); i++) line(m, fc.optJSONObject(i).optString("cause"), String.valueOf(fc.optJSONObject(i).optInt("count")));
                }
                JSONObject bt = j.optJSONObject("by_type");
                if (bt != null && bt.length() > 0) {
                    LinearLayout m = section("Filament by type");
                    for (Iterator<String> it = bt.keys(); it.hasNext(); ) { String k = it.next(); line(m, k, kg(bt.optDouble(k))); }
                }
                JSONObject es = j.optJSONObject("estimate");
                if (es != null) {
                    LinearLayout m = section("Estimated vs real time");
                    int off = es.optInt("avg_off_min");
                    m.addView(Ui.text(StatsActivity.this, "Over " + es.optInt("prints") + " finished prints they took " + es.optInt("avg_pct")
                            + "% of the estimate on average (" + Math.abs(off) + " min " + (off >= 0 ? "longer" : "shorter") + "). Pauses don't count.", 13, Ui.MUTED, false));
                    JSONArray rc = es.optJSONArray("recent");
                    for (int i = 0; rc != null && i < rc.length(); i++) {
                        JSONObject x = rc.optJSONObject(i);
                        line(m, x.optString("job"), Ui.mins(x.optDouble("est")) + " → " + Ui.mins(x.optDouble("real")));
                    }
                }
            }
        });
    }
}
