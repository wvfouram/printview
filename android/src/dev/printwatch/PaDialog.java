package dev.printwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

/**
 * Pressure advance (K) for one AMS slot or the external spool: type a K value you already know and it
 * is saved on the printer and assigned to the slot, no calibration print. Also lists the K values saved
 * on the printer for this material, to pick one or delete it.
 */
final class PaDialog {
    private PaDialog() { }

    static void show(final Activity a, final JSONObject t, final Runnable after) {
        final Handler ui = new Handler(Looper.getMainLooper());
        final int slot = t.optInt("slot");
        final String fid = t.optString("idx", "");
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(a, 20);
        box.setPadding(p, Ui.dp(a, 8), p, 0);

        double k = t.isNull("k") ? -1 : t.optDouble("k", -1);
        TextView cur = Ui.text(a, (k >= 0 ? String.format(Locale.US, "Current K: %.3f", k) : "Current K: not reported")
                + "\n" + (t.optString("type").isEmpty() ? "No material set" : t.optString("type")), 14, Ui.MUTED, false);
        box.addView(cur);

        final EditText kIn = new EditText(a);
        kIn.setHint("K value, e.g. 0.032");
        kIn.setHintTextColor(Ui.FAINT);
        kIn.setTextColor(Ui.TEXT);
        kIn.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        if (k > 0) kIn.setText(String.format(Locale.US, "%.3f", k));
        box.addView(kIn);
        final EditText nameIn = new EditText(a);
        nameIn.setHint("Name (optional), e.g. Overture PETG black");
        nameIn.setHintTextColor(Ui.FAINT);
        nameIn.setTextColor(Ui.TEXT);
        nameIn.setSingleLine(true);
        box.addView(nameIn);

        TextView h = Ui.heading(a, "Saved on the printer");
        h.setPadding(0, Ui.dp(a, 16), 0, Ui.dp(a, 4));
        box.addView(h);
        final LinearLayout list = new LinearLayout(a);
        list.setOrientation(LinearLayout.VERTICAL);
        box.addView(list);
        final TextView loading = Ui.text(a, "Loading...", 13, Ui.MUTED, false);
        list.addView(loading);

        android.widget.ScrollView sv = new android.widget.ScrollView(a);
        sv.addView(box);
        final AlertDialog dlg = new AlertDialog.Builder(a, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Pressure advance · " + (slot == 254 ? "external spool" : "slot " + t.optInt("tray")))
                .setView(sv)
                .setNegativeButton("Close", null)
                .setPositiveButton("Save K", null)
                .create();
        dlg.setOnShowListener(new DialogInterface.OnShowListener() {
            public void onShow(DialogInterface d) {
                dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        double val;
                        try { val = Double.parseDouble(kIn.getText().toString().trim()); } catch (Exception e) { toast(a, "Type a K value"); return; }
                        if (val < 0 || val > 2) { toast(a, "K is usually 0.01-0.1"); return; }
                        try {
                            JSONObject b = new JSONObject().put("action", "set").put("slot", slot).put("k", val)
                                    .put("name", nameIn.getText().toString().trim());
                            post(a, ui, b, "K " + String.format(Locale.US, "%.3f", val) + " saved to this slot", dlg, after);
                        } catch (Exception ignored) { }
                    }
                });
            }
        });
        dlg.show();

        new Thread(new Runnable() {
            public void run() {
                JSONObject r = null; String err = null;
                try {
                    Api.Resp res = Api.get(a, "/api/pa", null, 15000);
                    r = new JSONObject(res.text());
                    if (!r.optBoolean("ok")) err = r.optString("error", "HTTP " + res.code);
                } catch (Exception e) { err = "Can't reach PrintWatch"; }
                final JSONObject fr = r; final String fe = err;
                ui.post(new Runnable() {
                    public void run() {
                        list.removeAllViews();
                        if (fe != null) { list.addView(Ui.text(a, fe, 13, Ui.DANGER, false)); return; }
                        if (!fr.optBoolean("table")) {
                            list.addView(Ui.text(a, "Your firmware keeps K on each slot (no saved list). Saving writes it straight to this slot.", 13, Ui.MUTED, false));
                            return;
                        }
                        JSONArray e = fr.optJSONArray("entries");
                        int shown = 0;
                        for (int i = 0; e != null && i < e.length(); i++) {
                            final JSONObject en = e.optJSONObject(i);
                            if (en == null || (!fid.isEmpty() && !fid.equals(en.optString("filament_id")))) continue;
                            shown++;
                            boolean using = en.optInt("cali_idx") == t.optInt("cali_idx", -99);
                            LinearLayout row = Ui.row(a);
                            row.setPadding(0, Ui.dp(a, 8), 0, Ui.dp(a, 8));
                            TextView nm = Ui.text(a, en.optString("name") + String.format(Locale.US, "\nK %.3f", en.optDouble("k"))
                                    + (using ? "  · in use" : ""), 14, using ? Ui.ACCENT : Ui.TEXT, false);
                            row.addView(nm, Ui.weight(1));
                            TextView use = Ui.text(a, "Use", 14, Ui.ACCENT, true);
                            use.setPadding(Ui.dp(a, 12), Ui.dp(a, 8), Ui.dp(a, 12), Ui.dp(a, 8));
                            use.setOnClickListener(new View.OnClickListener() {
                                public void onClick(View v) {
                                    try {
                                        post(a, ui, new JSONObject().put("action", "select").put("slot", slot)
                                                .put("cali_idx", en.optInt("cali_idx")).put("filament_id", en.optString("filament_id")),
                                                "Slot now uses K " + String.format(Locale.US, "%.3f", en.optDouble("k")), dlg, after);
                                    } catch (Exception ignored) { }
                                }
                            });
                            row.addView(use);
                            TextView del = Ui.text(a, "✕", 16, Ui.FAINT, false);
                            del.setPadding(Ui.dp(a, 10), Ui.dp(a, 8), Ui.dp(a, 4), Ui.dp(a, 8));
                            del.setOnClickListener(new View.OnClickListener() {
                                public void onClick(View v) {
                                    new AlertDialog.Builder(a, android.R.style.Theme_Material_Dialog_Alert)
                                            .setTitle("Delete " + en.optString("name") + "?")
                                            .setNegativeButton("Cancel", null)
                                            .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                                                public void onClick(DialogInterface d, int w) {
                                                    try {
                                                        post(a, ui, new JSONObject().put("action", "delete").put("cali_idx", en.optInt("cali_idx"))
                                                                .put("filament_id", en.optString("filament_id")), "Deleted", dlg, after);
                                                    } catch (Exception ignored) { }
                                                }
                                            }).show();
                                }
                            });
                            row.addView(del);
                            list.addView(row);
                        }
                        if (shown == 0) list.addView(Ui.text(a, "None saved for this material yet.", 13, Ui.MUTED, false));
                    }
                });
            }
        }).start();
    }

    private static void post(final Activity a, final Handler ui, final JSONObject body, final String okMsg,
                             final AlertDialog dlg, final Runnable after) {
        toast(a, "Sending...");
        new Thread(new Runnable() {
            public void run() {
                String msg;
                boolean ok = false;
                try {
                    Api.Resp r = Api.post(a, "/api/pa", body.toString());
                    JSONObject j = new JSONObject(r.text());
                    ok = j.optBoolean("ok");
                    msg = ok ? okMsg : j.optString("error", "HTTP " + r.code);
                } catch (Exception e) { msg = "Can't reach PrintWatch"; }
                final String m = msg; final boolean fok = ok;
                ui.post(new Runnable() {
                    public void run() {
                        toast(a, m);
                        if (fok) { dlg.dismiss(); if (after != null) after.run(); }
                    }
                });
            }
        }).start();
    }

    private static void toast(Activity a, String m) {
        Toast.makeText(a, m, Toast.LENGTH_LONG).show();
    }
}
