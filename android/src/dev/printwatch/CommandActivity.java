package dev.printwatch;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;

/**
 * Command center for the public web link. This phone is paired with the Pi, so it has
 * master powers with no code: freeze everyone on the general code, change that code,
 * see who is logged in and log people out.
 */
public class CommandActivity extends Base {
    private Switch freeze;
    private TextView freezeTxt, err;
    private LinearLayout list;
    private EditText code;
    private boolean setting;
    private TextView exTxt, exChip;
    private EditText exH, exS;
    private Button exGo, exStop;
    private LinearLayout exSet;
    private boolean running;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Context c = this;
        LinearLayout r = page("Back", "Command center");

        err = Ui.text(c, "", 13.5f, Color.parseColor("#ffd7d4"), false);
        err.setBackground(Ui.box(c, Color.parseColor("#2b1514"), 0, 16));
        err.setPadding(Ui.dp(c, 16), Ui.dp(c, 12), Ui.dp(c, 16), Ui.dp(c, 12));
        err.setVisibility(View.GONE);
        LinearLayout.LayoutParams el = new LinearLayout.LayoutParams(-1, -2);
        el.topMargin = Ui.dp(c, 12);
        r.addView(err, el);

        TextView intro = Ui.text(c, "Controls for the public web link. This phone has full command, no code needed.", 13, Ui.MUTED, false);
        intro.setPadding(0, Ui.dp(c, 10), 0, 0);
        r.addView(intro);

        // freeze
        LinearLayout fc = Ui.card(c);
        LinearLayout fr = Ui.row(c);
        LinearLayout ft = new LinearLayout(c);
        ft.setOrientation(LinearLayout.VERTICAL);
        ft.addView(Ui.text(c, "Freeze everyone", 17, Ui.TEXT, true));
        freezeTxt = Ui.text(c, "People on the general code can only watch the camera.", 13, Ui.MUTED, false);
        freezeTxt.setPadding(0, Ui.dp(c, 4), Ui.dp(c, 10), 0);
        ft.addView(freezeTxt);
        fr.addView(ft, Ui.weight(1));
        freeze = new Switch(c);
        freeze.setThumbTintList(new ColorStateList(new int[][]{{android.R.attr.state_checked}, {}}, new int[]{Ui.DANGER, Ui.MUTED}));
        freeze.setTrackTintList(new ColorStateList(new int[][]{{android.R.attr.state_checked}, {}},
                new int[]{Ui.alpha(Ui.DANGER, 0.45f), Ui.LINE}));
        fr.addView(freeze);
        fc.addView(fr);
        r.addView(fc);
        freeze.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton bt, final boolean on) {
                if (setting) return;
                post("/api/camview/freeze", "{\"frozen\":" + on + "}", new Done<JSONObject>() {
                    public void run(JSONObject v, String e) {
                        if (e != null) { toast(e); load(); return; }
                        toast(on ? "Everyone else is frozen" : "Controls are back on for everyone");
                        load();
                    }
                });
            }
        });

        // X-axis exercise
        LinearLayout xc = Ui.card(c);
        LinearLayout xh = Ui.row(c);
        xh.addView(Ui.heading(c, "X-axis exercise"), Ui.weight(1));
        exChip = Ui.text(c, "-", 12, Ui.MUTED, true);
        exChip.setBackground(Ui.box(c, Ui.SURFACE2, 0, 99));
        exChip.setPadding(Ui.dp(c, 10), Ui.dp(c, 5), Ui.dp(c, 10), Ui.dp(c, 5));
        xh.addView(exChip);
        xc.addView(xh);
        exTxt = Ui.text(c, "Homes, lifts the nozzle 20 mm, then moves the toolhead back and forth on X only. Stops by itself, or if a print starts.", 13, Ui.MUTED, false);
        exTxt.setPadding(0, Ui.dp(c, 8), 0, Ui.dp(c, 8));
        xc.addView(exTxt);
        exSet = Ui.row(c);
        exSet.addView(Ui.text(c, "Hours ", 13, Ui.TEXT, false));
        exH = numBox(c, "24");
        exSet.addView(exH, new LinearLayout.LayoutParams(Ui.dp(c, 70), -2));
        exSet.addView(Ui.text(c, "   Speed mm/s ", 13, Ui.TEXT, false));
        exS = numBox(c, "100");
        exSet.addView(exS, new LinearLayout.LayoutParams(Ui.dp(c, 70), -2));
        xc.addView(exSet);
        LinearLayout xb = Ui.row(c);
        xb.setPadding(0, Ui.dp(c, 10), 0, 0);
        exGo = Ui.button(c, "Start", Ui.ACCENT, Color.parseColor("#1a1206"), 0);
        exStop = Ui.button(c, "Stop", Ui.alpha(Ui.DANGER, 0.14f), Ui.DANGER, 0);
        LinearLayout.LayoutParams gl1 = Ui.weight(1);
        gl1.rightMargin = Ui.dp(c, 8);
        xb.addView(exGo, gl1);
        xb.addView(exStop, Ui.weight(1));
        xc.addView(xb);
        r.addView(xc);
        exGo.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                final String hrs = exH.getText().toString().trim(), spd = exS.getText().toString().trim();
                confirm("Start X-axis exercise?", "The printer homes, lifts the nozzle, then moves X back and forth for " + hrs
                        + " h at " + spd + " mm/s. Keep the build plate clear.", "Start", new Runnable() {
                    public void run() {
                        post("/api/camview/exercise", "{\"action\":\"start\",\"hours\":" + num(hrs, "24") + ",\"speed\":" + num(spd, "100") + "}",
                                new Done<JSONObject>() {
                                    public void run(JSONObject v, String e) { toast(e == null ? "Exercise started" : e); load(); }
                                });
                    }
                });
            }
        });
        exStop.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                post("/api/camview/exercise", "{\"action\":\"stop\"}", new Done<JSONObject>() {
                    public void run(JSONObject v, String e) { toast(e == null ? "Stopping (finishes the last few strokes)" : e); load(); }
                });
            }
        });

        // general code
        LinearLayout cc = Ui.card(c);
        cc.addView(Ui.heading(c, "General access code"));
        TextView ch = Ui.text(c, "Changing it logs out everyone on the old code.", 13, Ui.MUTED, false);
        ch.setPadding(0, 0, 0, Ui.dp(c, 10));
        cc.addView(ch);
        LinearLayout cr = Ui.row(c);
        code = new EditText(c);
        code.setHint("New code");
        code.setHintTextColor(Ui.FAINT);
        code.setTextColor(Ui.TEXT);
        code.setSingleLine(true);
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        code.setBackground(Ui.box(c, Ui.SURFACE2, Ui.LINE, 12));
        code.setPadding(Ui.dp(c, 12), Ui.dp(c, 10), Ui.dp(c, 12), Ui.dp(c, 10));
        cr.addView(code, Ui.weight(1));
        Button go = Ui.button(c, "Change", Ui.ACCENT, Color.parseColor("#1a1206"), 0);
        go.setMinHeight(Ui.dp(c, 44));
        go.setMinimumHeight(Ui.dp(c, 44));
        go.setPadding(Ui.dp(c, 18), 0, Ui.dp(c, 18), 0);
        LinearLayout.LayoutParams gl = new LinearLayout.LayoutParams(-2, Ui.dp(c, 46));
        gl.leftMargin = Ui.dp(c, 10);
        cr.addView(go, gl);
        cc.addView(cr);
        r.addView(cc);
        go.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                final String n = code.getText().toString().trim();
                if (!n.matches("[A-Za-z0-9]{4,32}")) { toast("Use 4 to 32 letters or numbers"); return; }
                confirm("Change the general code?", "New code: " + n + "\nEveryone using the old code will be logged out.", "Change",
                        new Runnable() {
                            public void run() {
                                post("/api/camview/code", "{\"code\":" + JSONObject.quote(n) + "}", new Done<JSONObject>() {
                                    public void run(JSONObject v, String e) {
                                        if (e != null) { toast(e); return; }
                                        code.setText("");
                                        toast("Code changed to " + n);
                                        load();
                                    }
                                });
                            }
                        });
            }
        });

        // who is logged in
        LinearLayout lc = Ui.card(c);
        LinearLayout lh = Ui.row(c);
        lh.addView(Ui.heading(c, "Logged in now"), Ui.weight(1));
        Button ref = Ui.button(c, "Refresh", Ui.SURFACE2, Ui.TEXT, 0);
        ref.setTextSize(14);
        ref.setMinHeight(Ui.dp(c, 36));
        ref.setMinimumHeight(Ui.dp(c, 36));
        ref.setPadding(Ui.dp(c, 14), 0, Ui.dp(c, 14), 0);
        lh.addView(ref, new LinearLayout.LayoutParams(-2, Ui.dp(c, 38)));
        lc.addView(lh);
        list = new LinearLayout(c);
        list.setOrientation(LinearLayout.VERTICAL);
        lc.addView(list);
        r.addView(lc);
        ref.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { load(); } });
    }

    @Override
    protected void onResume() {
        super.onResume();
        running = true;
        tick();
    }

    @Override
    protected void onPause() {
        super.onPause();
        running = false;
    }

    private void tick() {
        if (!running) return;
        load();
        ui.postDelayed(new Runnable() { public void run() { tick(); } }, 10000);
    }

    private void load() {
        loadExercise();
        getJson("/api/camview/state", new Done<JSONObject>() {
            public void run(JSONObject s, String e) {
                if (e != null || s == null) {
                    err.setText(e == null ? "No answer" : e);
                    err.setVisibility(View.VISIBLE);
                    return;
                }
                err.setVisibility(View.GONE);
                render(s);
            }
        });
    }

    private void render(JSONObject s) {
        Context c = this;
        boolean frozen = s.optBoolean("frozen");
        setting = true;
        freeze.setChecked(frozen);
        setting = false;
        freezeTxt.setText(frozen ? "Frozen: people on the general code can only watch the camera."
                : "Off: everyone with the code has full control. Turn on to make them view-only.");
        freezeTxt.setTextColor(frozen ? Ui.DANGER : Ui.MUTED);

        list.removeAllViews();
        JSONArray a = s.optJSONArray("sessions");
        if (a == null || a.length() == 0) {
            TextView t = Ui.text(c, "Nobody is logged in on the web link.", 14, Ui.MUTED, false);
            t.setPadding(0, Ui.dp(c, 12), 0, 0);
            list.addView(t);
            return;
        }
        for (int i = 0; i < a.length(); i++) {
            final JSONObject r = a.optJSONObject(i);
            if (r == null) continue;
            boolean master = "master".equals(r.optString("role"));
            LinearLayout row = Ui.row(c);
            row.setPadding(0, Ui.dp(c, 12), 0, Ui.dp(c, 12));
            if (i > 0) {
                View line = new View(c);
                line.setBackgroundColor(Ui.LINE);
                list.addView(line, new LinearLayout.LayoutParams(-1, 1));
            }
            LinearLayout col = new LinearLayout(c);
            col.setOrientation(LinearLayout.VERTICAL);
            col.addView(Ui.text(c, r.optString("device", "Browser"), 15, Ui.TEXT, true));
            TextView sub = Ui.text(c, r.optString("ip", "?") + " · " + ago(r.optLong("seen_s")) + " · since "
                    + DateFormat.getDateInstance(DateFormat.SHORT).format(new Date(r.optLong("since") * 1000)), 12.5f, Ui.FAINT, false);
            sub.setPadding(0, Ui.dp(c, 3), 0, 0);
            col.addView(sub);
            row.addView(col, Ui.weight(1));
            TextView chip = Ui.text(c, master ? "master" : frozen ? "frozen" : "general", 12, master ? Ui.ACCENT : frozen ? Ui.DANGER : Ui.MUTED, true);
            chip.setBackground(Ui.box(c, Ui.SURFACE2, 0, 99));
            chip.setPadding(Ui.dp(c, 10), Ui.dp(c, 5), Ui.dp(c, 10), Ui.dp(c, 5));
            row.addView(chip);
            if (!master) {
                Button out = Ui.button(c, "Log out", Ui.alpha(Ui.DANGER, 0.14f), Ui.DANGER, 0);
                out.setTextSize(13);
                out.setMinHeight(Ui.dp(c, 34));
                out.setMinimumHeight(Ui.dp(c, 34));
                out.setPadding(Ui.dp(c, 12), 0, Ui.dp(c, 12), 0);
                LinearLayout.LayoutParams ol = new LinearLayout.LayoutParams(-2, Ui.dp(c, 36));
                ol.leftMargin = Ui.dp(c, 8);
                row.addView(out, ol);
                out.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        post("/api/camview/kick", "{\"id\":" + JSONObject.quote(r.optString("id")) + "}", new Done<JSONObject>() {
                            public void run(JSONObject v, String e) { toast(e == null ? "Logged out" : e); load(); }
                        });
                    }
                });
            }
            row.setGravity(Gravity.CENTER_VERTICAL);
            list.addView(row);
        }
    }

    private EditText numBox(Context c, String val) {
        EditText e = new EditText(c);
        e.setText(val);
        e.setTextColor(Ui.TEXT);
        e.setSingleLine(true);
        e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        return e;
    }

    private static String num(String s, String def) {
        try { return String.valueOf(Double.parseDouble(s)); } catch (Exception e) { return def; }
    }

    private void loadExercise() {
        getJson("/api/camview/exercise", new Done<JSONObject>() {
            public void run(JSONObject x, String e) {
                if (x == null) return;
                boolean on = x.optBoolean("running");
                exChip.setText(on ? "running" : "off");
                exChip.setTextColor(on ? Ui.OK : Ui.MUTED);
                exGo.setEnabled(!on); exGo.setAlpha(on ? 0.35f : 1f);
                exStop.setEnabled(on); exStop.setAlpha(on ? 1f : 0.35f);
                exSet.setVisibility(on ? View.GONE : View.VISIBLE);
                JSONArray rg = x.optJSONArray("range");
                if (on) {
                    long left = x.optLong("left_s");
                    exTxt.setText(x.optInt("passes") + " back-and-forths so far \u00B7 " + (left / 3600) + "h " + ((left % 3600) / 60) + "m left \u00B7 "
                            + x.optInt("speed") + " mm/s" + (rg != null ? " between X" + rg.optInt(0) + " and X" + rg.optInt(1) : ""));
                } else if (!x.optString("reason").isEmpty()) {
                    exTxt.setText("Last run: " + x.optInt("passes") + " back-and-forths, " + x.optString("reason") + ".");
                }
            }
        });
    }

    private static String ago(long s) {
        if (s < 60) return "active now";
        if (s < 3600) return (s / 60) + " min ago";
        if (s < 86400) return (s / 3600) + " h ago";
        return (s / 86400) + " d ago";
    }
}
