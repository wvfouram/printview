package dev.printwatch;

import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.List;

/** Grams left on each spool (Bambu tags report it themselves, others are typed in once) and price per kg. */
public class SpoolsActivity extends Base {
    private LinearLayout list, prices;
    private EditText cur;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Spools and prices");
        Context c = this;
        note(p, "Bambu spools with a tag report what's left by themselves (turn on \"Estimate remaining filament\" in Controls). "
                + "For other spools, type the grams on the spool once; each print takes off what it used. You're warned before a print if a spool won't last.");
        list = Ui.card(c);
        list.addView(Ui.heading(c, "Spools"));
        p.addView(list);
        prices = Ui.card(c);
        p.addView(prices);
        load();
    }

    private EditText field(String hint, boolean number) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(Ui.FAINT);
        e.setSingleLine(true);
        e.setTextSize(14);
        if (number) e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        e.setBackground(Ui.box(this, Ui.SURFACE2, Ui.LINE, 10));
        int pd = Ui.dp(this, 10);
        e.setPadding(pd, pd, pd, pd);
        return e;
    }

    private void setting(String json) {
        post("/api/settings", json, new Done<JSONObject>() {
            public void run(JSONObject v, String e) { toast(e == null ? "Saved" : e); if (e == null) load(); }
        });
    }

    private void load() {
        getJson("/api/spools", new Done<JSONObject>() {
            public void run(JSONObject j, String e) {
                Context c = SpoolsActivity.this;
                while (list.getChildCount() > 1) list.removeViewAt(1);
                if (e != null) { list.addView(Ui.text(c, e, 13, Ui.DANGER, false)); return; }
                JSONArray a = j.optJSONArray("spools");
                int shown = 0;
                for (int i = 0; a != null && i < a.length(); i++) {
                    final JSONObject r = a.optJSONObject(i);
                    if (r.optBoolean("empty")) continue;
                    shown++;
                    LinearLayout row = Ui.row(c);
                    row.setPadding(0, Ui.dp(c, 10), 0, Ui.dp(c, 10));
                    View dot = new View(c);
                    int col = Ui.SURFACE2;
                    try { col = Color.parseColor(r.optString("color", "#1f2226")); } catch (Exception ignored) { }
                    dot.setBackground(Ui.box(c, col, Ui.LINE, 9));
                    LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(Ui.dp(c, 18), Ui.dp(c, 18));
                    dl.rightMargin = Ui.dp(c, 10);
                    row.addView(dot, dl);
                    LinearLayout info = new LinearLayout(c);
                    info.setOrientation(LinearLayout.VERTICAL);
                    int slot = r.optInt("slot");
                    String unit = r.optString("unit");
                    String where = slot == 254 ? "External" : (r.optInt("unit") >= 128 ? "AMS HT" : "AMS " + unit) + " · " + r.optInt("tray");
                    info.addView(Ui.text(c, where + " · " + r.optString("type"), 15, Ui.TEXT, true));
                    String left = r.isNull("left_g") ? "Unknown, type the grams" : r.optInt("left_g") + " g left" + ("rfid".equals(r.optString("source")) ? " (from the spool's tag)" : "");
                    boolean low = !r.isNull("left_g") && r.optInt("left_g") < 0.15 * r.optInt("full_g", 1000);
                    info.addView(Ui.text(c, left, 12.5f, low ? Ui.DANGER : Ui.MUTED, false));
                    row.addView(info, Ui.weight(1));
                    if (!"rfid".equals(r.optString("source"))) {
                        Button set = Ui.button(c, "Set", Ui.ACCENT, 0xff1a1206, 0);
                        set.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { askGrams(r); } });
                        row.addView(set);
                    }
                    list.addView(row);
                }
                if (shown == 0) list.addView(Ui.text(c, "No spools loaded.", 13, Ui.MUTED, false));
                drawPrices(j);
            }
        });
    }

    private void askGrams(final JSONObject r) {
        final EditText e = field("grams, a full 1 kg spool is 1000", true);
        new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Grams on this spool").setView(e).setNegativeButton("Cancel", null)
                .setPositiveButton("Save", new android.content.DialogInterface.OnClickListener() {
                    public void onClick(android.content.DialogInterface d, int w) {
                        String v = e.getText().toString().trim();
                        if (v.isEmpty()) return;
                        post("/api/spools/set", "{\"slot\":" + r.optInt("slot") + ",\"grams\":" + v + "}", new Done<JSONObject>() {
                            public void run(JSONObject x, String err) { toast(err == null ? "Saved" : err); load(); }
                        });
                    }
                }).show();
    }

    private void drawPrices(JSONObject j) {
        Context c = this;
        prices.removeAllViews();
        prices.addView(Ui.heading(c, "Price per kg"));
        prices.addView(Ui.text(c, "Used for the cost of each print. A type not listed uses its base type (PLA Matte uses PLA).", 12.5f, Ui.MUTED, false));
        LinearLayout cr = Ui.row(c);
        cr.setPadding(0, Ui.dp(c, 10), 0, 0);
        cr.addView(Ui.text(c, "Currency", 14, Ui.TEXT, false), Ui.weight(1));
        cur = field("$", false);
        cur.setText(j.optString("currency", "$"));
        cr.addView(cur, new LinearLayout.LayoutParams(Ui.dp(c, 80), -2));
        Button cs = Ui.button(c, "Save", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        cs.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { setting("{\"currency\":" + JSONObject.quote(cur.getText().toString()) + "}"); } });
        cr.addView(cs);
        prices.addView(cr);
        JSONObject pr = j.optJSONObject("prices");
        List<String> keys = new ArrayList<>();
        for (Iterator<String> it = pr == null ? null : pr.keys(); it != null && it.hasNext(); ) keys.add(it.next());
        Collections.sort(keys);
        for (final String k : keys) {
            LinearLayout r = Ui.row(c);
            r.setPadding(0, Ui.dp(c, 8), 0, 0);
            r.addView(Ui.text(c, k, 14, Ui.TEXT, true), Ui.weight(1));
            final EditText e = field("price", true);
            e.setText(pr.optString(k));
            r.addView(e, new LinearLayout.LayoutParams(Ui.dp(c, 90), -2));
            Button s = Ui.button(c, "Save", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
            s.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
                String val = e.getText().toString().trim();
                setting("{\"prices\":{" + JSONObject.quote(k) + ":" + (val.isEmpty() ? "null" : val) + "}}");
            } });
            r.addView(s);
            prices.addView(r);
        }
        LinearLayout add = Ui.row(c);
        add.setPadding(0, Ui.dp(c, 12), 0, 0);
        final EditText t = field("Type, like PA6-CF", false);
        add.addView(t, Ui.weight(1));
        final EditText v = field("price", true);
        LinearLayout.LayoutParams vl = new LinearLayout.LayoutParams(Ui.dp(c, 90), -2);
        vl.leftMargin = Ui.dp(c, 6);
        add.addView(v, vl);
        Button ab = Ui.button(c, "Add", Ui.ACCENT, 0xff1a1206, 0);
        ab.setOnClickListener(new View.OnClickListener() { public void onClick(View x) {
            String tt = t.getText().toString().trim(), vv = v.getText().toString().trim();
            if (tt.isEmpty() || vv.isEmpty()) { toast("Type a filament type and a price"); return; }
            setting("{\"prices\":{" + JSONObject.quote(tt) + ":" + vv + "}}");
        } });
        add.addView(ab);
        prices.addView(add);
    }
}
