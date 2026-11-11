package dev.printwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.CompoundButton;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Every printer control the P1S accepts over LAN MQTT. Movement is locked while printing. */
public class ControlsActivity extends Activity {
    private CamPip pip;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newFixedThreadPool(2);
    private boolean running, busyCmd;
    private JSONObject printer;

    private final Button[] speed = new Button[4];
    private TextView speedNow, nozzleNow, bedNow, info, hms, motionLock, stepLabel;
    private final SeekBar[] fan = new SeekBar[3];
    private final TextView[] fanNow = new TextView[3];
    private static final String[] FAN_KEYS = {"part", "aux", "chamber"};
    private final boolean[] dragging = new boolean[3];
    private LinearLayout amsList, motionBox;
    private Button lightBtn;
    private EditText console;
    private float step = 10;
    private final Button[] stepBtn = new Button[3];
    private static final float[] STEPS = {1, 10, 50};
    private String amsSig = "";
    private Switch optRecovery, optRefill, optStartup, optInsert, optRemain;
    private android.widget.CheckBox calBed, calVib, calMotor;
    private Button calBtn;
    private TextView sdLine;
    private boolean settingOpts;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(Ui.BG);
        getWindow().setNavigationBarColor(Ui.BG);
        setContentView(build());
    }

    @Override
    protected void onResume() {
        super.onResume();
        pip = CamPip.show(this);
        running = true;
        poll();
    }

    @Override
    protected void onPause() {
        if (pip != null) { pip.hide(); pip = null; }
        super.onPause();
        running = false;
    }

    // ------------------------------------------------------------------ layout
    private View build() {
        Context c = this;
        ScrollView sv = new ScrollView(c);
        sv.setBackgroundColor(Ui.BG);
        LinearLayout root = new LinearLayout(c);
        root.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 14);
        root.setPadding(p, Ui.dp(c, 8), p, Ui.dp(c, 28));
        sv.addView(root);

        LinearLayout head = Ui.row(c);
        Button back = flat("‹ Live");
        back.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { finish(); } });
        head.addView(back);
        head.addView(Ui.text(c, "Printer controls", 18, Ui.TEXT, true), Ui.weight(1));
        lightBtn = small("Light", Ui.SURFACE2, Ui.TEXT);
        lightBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                boolean on = printer != null && printer.optBoolean("light", false);
                send("{\"action\":\"" + (on ? "light_off" : "light_on") + "\"}", on ? "Light off" : "Light on");
            }
        });
        head.addView(lightBtn, new LinearLayout.LayoutParams(-2, Ui.dp(c, 40)));
        root.addView(head);

        // speed
        LinearLayout sp = Ui.card(c);
        LinearLayout sh = Ui.row(c);
        sh.addView(Ui.heading(c, "Print speed"), Ui.weight(1));
        speedNow = mono("");
        sh.addView(speedNow);
        sp.addView(sh);
        sp.addView(Ui.space(c, 10));
        LinearLayout seg = Ui.row(c);
        String[] names = {"Silent", "Standard", "Sport", "Ludicrous"};
        for (int i = 0; i < 4; i++) {
            final int lvl = i + 1;
            Button bt = small(names[i], Ui.SURFACE2, Ui.MUTED);
            bt.setTextSize(13);
            bt.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    send("{\"action\":\"speed\",\"level\":" + lvl + "}", "Speed: " + ((Button) v).getText());
                }
            });
            speed[i] = bt;
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 6);
            seg.addView(bt, lp);
        }
        sp.addView(seg);
        root.addView(sp);

        // temperatures
        LinearLayout tc = Ui.card(c);
        tc.addView(Ui.heading(c, "Temperatures"));
        nozzleNow = tempRow(tc, "Nozzle", "nozzle", 5);
        bedNow = tempRow(tc, "Bed", "bed", 5);
        tc.addView(Ui.space(c, 10));
        LinearLayout pre = Ui.row(c);
        final String[][] presets = {{"PLA", "220", "55"}, {"PETG", "250", "70"}, {"ABS", "260", "90"}, {"TPU", "230", "40"}};
        for (int i = 0; i < presets.length; i++) {
            final String[] pr = presets[i];
            Button bt = small(pr[0], Ui.SURFACE2, Ui.TEXT);
            bt.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { setTemps(pr[0], Integer.parseInt(pr[1]), Integer.parseInt(pr[2])); }
            });
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 6);
            pre.addView(bt, lp);
        }
        tc.addView(pre);
        tc.addView(Ui.space(c, 8));
        Button cool = Ui.button(c, "Cool down", Ui.SURFACE2, Ui.INFO, Ui.LINE);
        cool.setTextSize(15);
        cool.setMinHeight(Ui.dp(c, 46));
        cool.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                confirm("Cool down?", "Sets nozzle and bed to 0°." + (busy() ? " A print is running, so this will ruin it." : ""),
                        "Cool down", new Runnable() { public void run() { setTemps("Cool down", 0, 0); } });
            }
        });
        tc.addView(cool);
        root.addView(tc);

        // fans
        LinearLayout fc = Ui.card(c);
        fc.addView(Ui.heading(c, "Fans"));
        String[] fanNames = {"Part cooling", "Aux (side)", "Chamber"};
        for (int i = 0; i < 3; i++) fanRow(fc, i, fanNames[i]);
        root.addView(fc);

        // AMS
        LinearLayout ac = Ui.card(c);
        LinearLayout ah = Ui.row(c);
        ah.addView(Ui.heading(c, "AMS"), Ui.weight(1));
        ac.addView(ah);
        amsList = new LinearLayout(c);
        amsList.setOrientation(LinearLayout.VERTICAL);
        ac.addView(amsList);
        LinearLayout ab = Ui.row(c);
        ab.setPadding(0, Ui.dp(c, 10), 0, 0);
        Button unload = small("Unload", Ui.SURFACE2, Ui.TEXT);
        unload.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                confirm("Unload filament?", "Retracts the loaded filament back to the AMS.", "Unload",
                        new Runnable() { public void run() { send("{\"action\":\"ams_unload\"}", "Unloading..."); } });
            }
        });
        Button retry = small("AMS retry", Ui.SURFACE2, Ui.TEXT);
        retry.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { send("{\"action\":\"ams_resume\"}", "AMS: retry sent"); }
        });
        LinearLayout.LayoutParams ul = Ui.weight(1);
        ul.rightMargin = Ui.dp(c, 6);
        ab.addView(unload, ul);
        ab.addView(retry, Ui.weight(1));
        ac.addView(ab);
        root.addView(ac);

        // movement
        LinearLayout mc = Ui.card(c);
        LinearLayout mh = Ui.row(c);
        mh.addView(Ui.heading(c, "Move"), Ui.weight(1));
        stepLabel = mono("");
        mh.addView(stepLabel);
        mc.addView(mh);
        motionLock = Ui.text(c, "Locked while a print is running.", 13, Ui.ACCENT, false);
        motionLock.setPadding(0, Ui.dp(c, 6), 0, 0);
        mc.addView(motionLock);
        motionBox = new LinearLayout(c);
        motionBox.setOrientation(LinearLayout.VERTICAL);
        mc.addView(motionBox);
        buildMotion(motionBox);
        root.addView(mc);

        // console
        LinearLayout cc = Ui.card(c);
        cc.addView(Ui.heading(c, "G-code console"));
        console = new EditText(c);
        console.setHint("e.g. M106 P1 S128");
        console.setHintTextColor(Ui.FAINT);
        console.setTextColor(Ui.TEXT);
        console.setTypeface(Ui.MONO);
        console.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        console.setMinLines(2);
        console.setBackground(Ui.box(c, Ui.SURFACE2, Ui.LINE, 10));
        int cp = Ui.dp(c, 10);
        console.setPadding(cp, cp, cp, cp);
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-1, -2);
        cl.topMargin = Ui.dp(c, 10);
        cc.addView(console, cl);
        Button sendG = Ui.button(c, "Send", Ui.ACCENT, Color.parseColor("#111111"), 0);
        sendG.setMinHeight(Ui.dp(c, 46));
        sendG.setTextSize(15);
        LinearLayout.LayoutParams sl = new LinearLayout.LayoutParams(-1, -2);
        sl.topMargin = Ui.dp(c, 8);
        cc.addView(sendG, sl);
        sendG.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                final String g = console.getText().toString().trim();
                if (g.isEmpty()) return;
                confirm("Send G-code?", g + (busy() ? "\n\nA print is running. Movement commands are blocked." : ""), "Send",
                        new Runnable() { public void run() { send("{\"action\":\"gcode\",\"gcode\":" + JSONObject.quote(g) + "}", "Sent"); } });
            }
        });
        TextView cn = Ui.text(c, "Goes straight to the printer. Moves (G0/G1/G28...) are refused while printing.", 12, Ui.MUTED, false);
        cn.setPadding(0, Ui.dp(c, 6), 0, 0);
        cc.addView(cn);
        root.addView(cc);

        // printer options
        LinearLayout opt = Ui.card(c);
        opt.addView(Ui.heading(c, "Printer options"));
        optRecovery = optSwitch(opt, "Auto-recover from step loss", "Re-home and continue if the toolhead slips",
                "{\"action\":\"option\",\"name\":\"auto_recovery\",\"value\":%b}");
        optRefill = optSwitch(opt, "AMS auto-refill", "Switch to a matching spool when one runs out",
                "{\"action\":\"option\",\"name\":\"auto_switch_filament\",\"value\":%b}");
        optStartup = optSwitch(opt, "Read RFID at power-on", "AMS scans Bambu spools when it starts", null);
        optInsert = optSwitch(opt, "Read RFID on insert", "AMS scans a Bambu spool when you load it", null);
        optRemain = optSwitch(opt, "Estimate remaining filament", "Track how much is left on each spool", null);
        sdLine = Ui.text(c, "", 12, Ui.MUTED, false);
        sdLine.setPadding(0, Ui.dp(c, 10), 0, 0);
        opt.addView(sdLine);
        root.addView(opt);

        // calibration
        LinearLayout cal = Ui.card(c);
        cal.addView(Ui.heading(c, "Calibration"));
        calBed = check(cal, "Bed leveling", true);
        calVib = check(cal, "Vibration compensation", true);
        calMotor = check(cal, "Motor noise cancellation", false);
        calBtn = Ui.button(c, "Run calibration", Ui.SURFACE2, Ui.ACCENT, Ui.LINE);
        calBtn.setTextSize(15);
        calBtn.setMinHeight(Ui.dp(c, 46));
        LinearLayout.LayoutParams cbl = new LinearLayout.LayoutParams(-1, -2);
        cbl.topMargin = Ui.dp(c, 8);
        cal.addView(calBtn, cbl);
        calBtn.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            final boolean b1 = calBed.isChecked(), b2 = calVib.isChecked(), b3 = calMotor.isChecked();
            if (!b1 && !b2 && !b3) { toast("Pick at least one"); return; }
            confirm("Run calibration?", "Takes several minutes. Make sure the bed is empty.", "Run", new Runnable() {
                public void run() {
                    send("{\"action\":\"calibrate\",\"bed\":" + b1 + ",\"vibration\":" + b2 + ",\"motor\":" + b3 + "}", "Calibration started");
                }
            });
        } });
        root.addView(cal);

        // info
        LinearLayout ic = Ui.card(c);
        ic.addView(Ui.heading(c, "Printer"));
        info = Ui.text(c, "", 13, Ui.TEXT, false);
        info.setTypeface(Ui.MONO);
        info.setLineSpacing(Ui.dp(c, 3), 1f);
        info.setPadding(0, Ui.dp(c, 8), 0, 0);
        ic.addView(info);
        hms = Ui.text(c, "", 13, Ui.DANGER, false);
        hms.setTypeface(Ui.MONO);
        ic.addView(hms);
        root.addView(ic);
        return sv;
    }

    private TextView tempRow(LinearLayout parent, String label, final String key, final int delta) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 10), 0, 0);
        LinearLayout col = new LinearLayout(c);
        col.setOrientation(LinearLayout.VERTICAL);
        col.addView(Ui.text(c, label, 15, Ui.TEXT, true));
        TextView now = mono("--");
        col.addView(now);
        r.addView(col, Ui.weight(1));
        Button minus = small("−" + delta, Ui.SURFACE2, Ui.TEXT);
        Button set = small("Set", Ui.SURFACE2, Ui.ACCENT);
        Button plus = small("+" + delta, Ui.SURFACE2, Ui.TEXT);
        minus.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { nudge(key, -delta); } });
        plus.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { nudge(key, delta); } });
        set.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { askTemp(key); } });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(Ui.dp(c, 58), Ui.dp(c, 42));
        lp.leftMargin = Ui.dp(c, 6);
        r.addView(minus, lp);
        r.addView(set, new LinearLayout.LayoutParams(lp));
        r.addView(plus, new LinearLayout.LayoutParams(lp));
        ((LinearLayout.LayoutParams) set.getLayoutParams()).leftMargin = Ui.dp(c, 6);
        ((LinearLayout.LayoutParams) plus.getLayoutParams()).leftMargin = Ui.dp(c, 6);
        parent.addView(r);
        return now;
    }

    private void fanRow(LinearLayout parent, final int i, String label) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 10), 0, 0);
        r.addView(Ui.text(c, label, 14, Ui.TEXT, true), Ui.weight(1));
        fanNow[i] = mono("--");
        r.addView(fanNow[i]);
        parent.addView(r);
        SeekBar s = new SeekBar(c);
        s.setMax(10);
        s.setProgressTintList(android.content.res.ColorStateList.valueOf(Ui.INFO));
        s.setThumbTintList(android.content.res.ColorStateList.valueOf(Ui.INFO));
        s.setPadding(Ui.dp(c, 8), Ui.dp(c, 10), Ui.dp(c, 8), Ui.dp(c, 10));
        s.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar sb, int v, boolean user) { if (user) fanNow[i].setText(v * 10 + "%"); }
            public void onStartTrackingTouch(SeekBar sb) { dragging[i] = true; }
            public void onStopTrackingTouch(SeekBar sb) {
                dragging[i] = false;
                int pct = sb.getProgress() * 10;
                send("{\"action\":\"fan\",\"fan\":\"" + FAN_KEYS[i] + "\",\"percent\":" + pct + "}", "Fan " + pct + "%");
            }
        });
        fan[i] = s;
        parent.addView(s);
    }

    private void buildMotion(LinearLayout m) {
        Context c = this;
        LinearLayout steps = Ui.row(c);
        steps.setPadding(0, Ui.dp(c, 10), 0, 0);
        steps.addView(Ui.text(c, "Step", 14, Ui.MUTED, false), Ui.weight(1));
        for (int i = 0; i < 3; i++) {
            final int idx = i;
            Button b = small((int) STEPS[i] + " mm", Ui.SURFACE2, Ui.MUTED);
            b.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { step = STEPS[idx]; paintSteps(); } });
            stepBtn[i] = b;
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(Ui.dp(c, 70), Ui.dp(c, 40));
            lp.leftMargin = Ui.dp(c, 6);
            steps.addView(b, lp);
        }
        m.addView(steps);
        paintSteps();

        LinearLayout pad = Ui.row(c);
        pad.setPadding(0, Ui.dp(c, 12), 0, 0);
        // XY cross
        LinearLayout xy = new LinearLayout(c);
        xy.setOrientation(LinearLayout.VERTICAL);
        xy.setGravity(Gravity.CENTER_HORIZONTAL);
        xy.addView(jogBtn("Y+", "Y", 1));
        LinearLayout mid = Ui.row(c);
        mid.addView(jogBtn("X−", "X", -1));
        Button home = small("Home", Ui.ACCENT, Color.parseColor("#111111"));
        home.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                confirm("Home all axes?", "The toolhead and bed move to their home positions.", "Home",
                        new Runnable() { public void run() { send("{\"action\":\"home\"}", "Homing..."); } });
            }
        });
        LinearLayout.LayoutParams hl = new LinearLayout.LayoutParams(Ui.dp(c, 64), Ui.dp(c, 56));
        hl.setMargins(Ui.dp(c, 6), 0, Ui.dp(c, 6), 0);
        mid.addView(home, hl);
        mid.addView(jogBtn("X+", "X", 1));
        xy.addView(mid);
        xy.addView(jogBtn("Y−", "Y", -1));
        pad.addView(xy, Ui.weight(1));
        // Z column
        LinearLayout z = new LinearLayout(c);
        z.setOrientation(LinearLayout.VERTICAL);
        z.setGravity(Gravity.CENTER_HORIZONTAL);
        z.addView(jogBtn("Bed ↑", "Z", -1));
        TextView zl = Ui.text(c, "Z", 13, Ui.MUTED, true);
        zl.setGravity(Gravity.CENTER);
        zl.setPadding(0, Ui.dp(c, 6), 0, Ui.dp(c, 6));
        z.addView(zl);
        z.addView(jogBtn("Bed ↓", "Z", 1));
        pad.addView(z);
        m.addView(pad);

        LinearLayout ex = Ui.row(c);
        ex.setPadding(0, Ui.dp(c, 12), 0, 0);
        Button retract = small("Retract 10 mm", Ui.SURFACE2, Ui.TEXT);
        Button extrude = small("Extrude 10 mm", Ui.SURFACE2, Ui.TEXT);
        retract.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            send("{\"action\":\"extrude\",\"mm\":-10}", "Retracting");
        } });
        extrude.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            send("{\"action\":\"extrude\",\"mm\":10}", "Extruding");
        } });
        LinearLayout.LayoutParams rl = Ui.weight(1);
        rl.rightMargin = Ui.dp(c, 6);
        ex.addView(retract, rl);
        ex.addView(extrude, Ui.weight(1));
        m.addView(ex);
        TextView en = Ui.text(c, "Extruding needs the nozzle at 170\u00B0 or hotter.", 12, Ui.MUTED, false);
        en.setPadding(0, Ui.dp(c, 4), 0, 0);
        m.addView(en);

        Button off = small("Motors off", Ui.SURFACE2, Ui.TEXT);
        off.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { send("{\"action\":\"motors_off\"}", "Motors off"); }
        });
        LinearLayout.LayoutParams ol = new LinearLayout.LayoutParams(-1, Ui.dp(c, 44));
        ol.topMargin = Ui.dp(c, 12);
        m.addView(off, ol);
    }

    private Button jogBtn(String label, final String axis, final int dir) {
        Button b = small(label, Ui.SURFACE2, Ui.TEXT);
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                float mm = step * dir;
                send("{\"action\":\"jog\",\"axis\":\"" + axis + "\",\"mm\":" + mm + "}", axis + (mm > 0 ? " +" : " ") + mm + " mm");
            }
        });
        b.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(this, 76), Ui.dp(this, 56)));
        return b;
    }

    private void paintSteps() {
        for (int i = 0; i < 3; i++) {
            boolean on = STEPS[i] == step;
            stepBtn[i].setBackground(Ui.box(this, on ? Ui.LINE : Ui.SURFACE2, 0, 10));
            stepBtn[i].setTextColor(on ? Ui.TEXT : Ui.MUTED);
        }
        if (stepLabel != null) stepLabel.setText((int) step + " mm steps");
    }

    private Switch optSwitch(LinearLayout parent, String title, String sub, final String jsonFmt) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 12), 0, 0);
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        t.addView(Ui.text(c, title, 15, Ui.TEXT, true));
        t.addView(Ui.text(c, sub, 12, Ui.MUTED, false));
        r.addView(t, Ui.weight(1));
        final Switch s = new Switch(c);
        r.addView(s);
        parent.addView(r);
        s.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton b, boolean on) {
                if (settingOpts) return;
                if (jsonFmt != null) send(String.format(jsonFmt, on), on ? "On" : "Off");
                else send("{\"action\":\"ams_options\",\"startup_read\":" + optStartup.isChecked()
                        + ",\"tray_read\":" + optInsert.isChecked() + ",\"remain_calc\":" + optRemain.isChecked() + "}", "AMS settings saved");
            }
        });
        return s;
    }

    private android.widget.CheckBox check(LinearLayout parent, String label, boolean on) {
        android.widget.CheckBox cb = new android.widget.CheckBox(this);
        cb.setText(label);
        cb.setTextColor(Ui.TEXT);
        cb.setTextSize(15);
        cb.setChecked(on);
        cb.setPadding(Ui.dp(this, 6), Ui.dp(this, 6), 0, Ui.dp(this, 6));
        parent.addView(cb);
        return cb;
    }

    private void setOpt(Switch s, JSONObject o, String key) {
        if (o == null || o.isNull(key)) { s.setAlpha(0.5f); return; }
        s.setAlpha(1f);
        s.setChecked(o.optBoolean(key));
    }

    // ------------------------------------------------------------------ helpers
    private Button small(String s, int fill, int textColor) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(14);
        b.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        b.setTextColor(textColor);
        b.setStateListAnimator(null);
        b.setMinHeight(Ui.dp(this, 42));
        b.setMinimumHeight(Ui.dp(this, 42));
        b.setPadding(Ui.dp(this, 8), 0, Ui.dp(this, 8), 0);
        b.setBackground(Ui.box(this, fill, 0, 10));
        return b;
    }

    private Button flat(String s) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextColor(Ui.MUTED);
        b.setBackgroundColor(Color.TRANSPARENT);
        return b;
    }

    private TextView mono(String s) {
        TextView t = Ui.text(this, s, 13, Ui.MUTED, false);
        t.setTypeface(Ui.MONO);
        return t;
    }

    private boolean busy() {
        return printer != null && printer.optBoolean("busy");
    }

    private void confirm(String title, String msg, String ok, final Runnable action) {
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(title).setMessage(msg).setNegativeButton("Cancel", null)
                .setPositiveButton(ok, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) { action.run(); }
                }).show();
    }

    private void nudge(String key, int delta) {
        if (printer == null) return;
        double target = printer.isNull(key + "_target") ? 0 : printer.optDouble(key + "_target", 0);
        int max = key.equals("bed") ? 100 : 300;
        int v = (int) Math.max(0, Math.min(max, Math.round(target) + delta));
        send("{\"action\":\"temp\",\"target\":\"" + key + "\",\"value\":" + v + "}", (key.equals("bed") ? "Bed " : "Nozzle ") + v + "°");
    }

    private void askTemp(final String key) {
        final EditText in = new EditText(this);
        in.setInputType(InputType.TYPE_CLASS_NUMBER);
        in.setTextColor(Ui.TEXT);
        in.setHint(key.equals("bed") ? "0 - 100" : "0 - 300");
        android.widget.FrameLayout f = new android.widget.FrameLayout(this);
        int p = Ui.dp(this, 20);
        f.setPadding(p, Ui.dp(this, 8), p, 0);
        f.addView(in);
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(key.equals("bed") ? "Bed target °C" : "Nozzle target °C")
                .setView(f).setNegativeButton("Cancel", null)
                .setPositiveButton("Set", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        try {
                            int v = Integer.parseInt(in.getText().toString().trim());
                            send("{\"action\":\"temp\",\"target\":\"" + key + "\",\"value\":" + v + "}", "Set " + v + "°");
                        } catch (NumberFormatException ignored) { }
                    }
                }).show();
    }

    private void setTemps(final String name, final int nozzle, final int bed) {
        net.execute(new Runnable() {
            public void run() {
                String err = post("{\"action\":\"temp\",\"target\":\"nozzle\",\"value\":" + nozzle + "}");
                if (err == null) err = post("{\"action\":\"temp\",\"target\":\"bed\",\"value\":" + bed + "}");
                final String fe = err;
                ui.post(new Runnable() {
                    public void run() { toast(fe == null ? name + ": " + nozzle + "° / " + bed + "°" : fe); }
                });
            }
        });
    }

    /** Returns null on success, or an error message. Runs on a background thread. */
    private String post(String json) {
        try {
            Api.Resp r = Api.post(this, "/api/cmd", json);
            JSONObject j = new JSONObject(r.text());
            return j.optBoolean("ok") ? null : j.optString("error", "HTTP " + r.code);
        } catch (Exception e) {
            return "Can't reach PrintWatch";
        }
    }

    private void send(final String json, final String okMsg) {
        if (busyCmd) return;
        busyCmd = true;
        net.execute(new Runnable() {
            public void run() {
                final String err = post(json);
                ui.post(new Runnable() {
                    public void run() {
                        toast(err == null ? okMsg : err);
                        ui.postDelayed(new Runnable() { public void run() { busyCmd = false; } }, 400);
                    }
                });
            }
        });
    }

    private void toast(String m) {
        Toast.makeText(this, m, Toast.LENGTH_SHORT).show();
    }

    // ------------------------------------------------------------------ status
    private void poll() {
        if (!running) return;
        net.execute(new Runnable() {
            public void run() {
                JSONObject p = null;
                try {
                    Api.Resp r = Api.get(ControlsActivity.this, "/api/status", null, 6000);
                    if (r.code == 200) p = new JSONObject(r.text()).optJSONObject("printer");
                } catch (Exception ignored) { }
                final JSONObject fp = p;
                ui.post(new Runnable() {
                    public void run() {
                        if (fp != null) render(fp);
                        else info.setText("Can't reach PrintWatch at " + Api.base(ControlsActivity.this));
                        ui.postDelayed(new Runnable() { public void run() { poll(); } }, 1500);
                    }
                });
            }
        });
    }

    private void render(JSONObject p) {
        printer = p;
        boolean conn = p.optBoolean("connected");
        int lvl = p.isNull("speed_level") ? 0 : p.optInt("speed_level");
        for (int i = 0; i < 4; i++) {
            boolean on = lvl == i + 1;
            speed[i].setBackground(Ui.box(this, on ? Ui.ACCENT : Ui.SURFACE2, 0, 10));
            speed[i].setTextColor(on ? Color.parseColor("#111111") : Ui.MUTED);
        }
        speedNow.setText(p.isNull("speed_pct") ? "" : p.optInt("speed_pct") + "%");
        nozzleNow.setText(temps(p, "nozzle"));
        bedNow.setText(temps(p, "bed"));

        JSONObject fans = p.optJSONObject("fans");
        for (int i = 0; i < 3; i++) {
            if (fans == null || fans.isNull(FAN_KEYS[i])) { fanNow[i].setText("--"); continue; }
            int v = fans.optInt(FAN_KEYS[i]);
            if (!dragging[i]) {
                fanNow[i].setText(v + "%");
                fan[i].setProgress(Math.round(v / 10f));
            }
        }

        boolean light = p.optBoolean("light", false);
        lightBtn.setTextColor(light ? Ui.ACCENT : Ui.TEXT);

        boolean busy = p.optBoolean("busy");
        motionLock.setVisibility(busy ? View.VISIBLE : View.GONE);
        setEnabledDeep(motionBox, conn && !busy);

        renderAms(p.optJSONObject("ams"), busy);

        JSONObject o = p.optJSONObject("options");
        settingOpts = true;
        setOpt(optRecovery, o, "auto_recovery");
        setOpt(optRefill, o, "auto_switch_filament");
        setOpt(optStartup, o, "ams_startup_read");
        setOpt(optInsert, o, "ams_tray_read");
        setOpt(optRemain, o, "ams_remain_calc");
        settingOpts = false;
        sdLine.setText(o == null || o.isNull("sdcard") ? "" : "SD card: " + o.optString("sdcard"));
        calBtn.setEnabled(conn && !busy);
        calBtn.setAlpha(conn && !busy ? 1f : 0.4f);

        StringBuilder sb = new StringBuilder();
        sb.append("State     ").append(conn ? p.optString("state") : "OFFLINE");
        if (!p.isNull("stage")) sb.append("\nStage     ").append(p.optString("stage"));
        if (!p.isNull("speed_name")) sb.append("\nSpeed     ").append(p.optString("speed_name"));
        if (fans != null && !fans.isNull("heatbreak")) sb.append("\nHeatbreak ").append(fans.optInt("heatbreak")).append("% fan");
        if (!p.isNull("wifi")) sb.append("\nWi-Fi     ").append(p.optString("wifi"));
        if (!p.isNull("nozzle_diameter")) sb.append("\nNozzle    ").append(p.optString("nozzle_diameter")).append(" mm");
        if (p.optInt("print_error") != 0) sb.append("\nError     ").append(Integer.toHexString(p.optInt("print_error")).toUpperCase());
        info.setText(sb.toString());
        JSONArray h = p.optJSONArray("hms");
        if (h != null && h.length() > 0) {
            StringBuilder hs = new StringBuilder("\nPrinter alerts (tap to look up):");
            final java.util.List<String> codes = new java.util.ArrayList<>();
            for (int i = 0; i < h.length(); i++) { hs.append("\n").append(h.optString(i)); codes.add(h.optString(i)); }
            hms.setText(hs.toString());
            hms.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
                // HMS_0300_1200_0002_0001 style -> Bambu wiki page for that code
                String code = codes.get(0).replace("HMS_", "");
                String seg = code.length() == 17 ? code.substring(0, 4) + "_" + code.substring(4, 8) + "_" + code.substring(9, 13) + "_" + code.substring(13) : code;
                startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW,
                        android.net.Uri.parse("https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/" + seg)));
            } });
            hms.setVisibility(View.VISIBLE);
        } else hms.setVisibility(View.GONE);
    }

    private String temps(JSONObject p, String key) {
        if (p.isNull(key)) return "--";
        String s = Math.round(p.optDouble(key)) + "°";
        if (!p.isNull(key + "_target")) s += "  → " + Math.round(p.optDouble(key + "_target")) + "°";
        return s;
    }

    private void renderAms(JSONObject a, final boolean busy) {
        String sig = a == null ? "" : a.toString() + busy;
        if (sig.equals(amsSig)) return;
        amsSig = sig;
        amsList.removeAllViews();
        Context c = this;
        JSONArray units = a == null ? null : a.optJSONArray("units");
        for (int i = 0; units != null && i < units.length(); i++) {
            JSONObject u = units.optJSONObject(i);
            if (u == null) continue;
            StringBuilder sb = new StringBuilder("AMS " + u.optInt("unit"));
            if (!u.isNull("temp")) sb.append("  \u00B7  ").append(Math.round(u.optDouble("temp"))).append("\u00B0C");
            if (!u.isNull("humidity_pct") && u.optInt("humidity_pct") > 0) sb.append("  \u00B7  ").append(u.optInt("humidity_pct")).append("% RH");
            else if (!u.isNull("humidity_level")) sb.append("  \u00B7  humidity ").append(u.optInt("humidity_level")).append("/5");
            boolean drying = u.optBoolean("drying");
            if (drying) {
                int m = u.optInt("dry_min_left");
                sb.append("\nDrying \u00B7 ").append(m / 60).append("h ").append(String.format("%02d", m % 60)).append("m left");
            }
            TextView ut = Ui.text(c, sb.toString(), 13, drying ? Ui.ACCENT : Ui.TEXT, drying);
            ut.setTypeface(Ui.MONO, drying ? android.graphics.Typeface.BOLD : android.graphics.Typeface.NORMAL);
            ut.setPadding(0, Ui.dp(c, 8), 0, 0);
            amsList.addView(ut);
        }
        if (units != null && units.length() > 0) {
            TextView note = Ui.text(c, "Drying starts from the printer's screen; the P1S doesn't accept drying commands over the network.", 11, Ui.FAINT, false);
            note.setPadding(0, Ui.dp(c, 4), 0, 0);
            amsList.addView(note);
        }
        JSONArray trays = a == null ? null : a.optJSONArray("trays");
        if (trays == null || trays.length() == 0) {
            TextView t = Ui.text(c, "No AMS detected.", 13, Ui.MUTED, false);
            t.setPadding(0, Ui.dp(c, 8), 0, 0);
            amsList.addView(t);
            return;
        }
        for (int i = 0; i < trays.length(); i++) {
            final JSONObject t = trays.optJSONObject(i);
            if (t == null) continue;
            LinearLayout r = Ui.row(c);
            r.setPadding(Ui.dp(c, 10), Ui.dp(c, 8), Ui.dp(c, 10), Ui.dp(c, 8));
            r.setBackground(Ui.box(c, t.optBoolean("active") ? Color.parseColor("#262f2412") : Ui.SURFACE2,
                    t.optBoolean("active") ? Ui.ACCENT : 0, 10));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = Ui.dp(c, 8);
            View sw = new View(c);
            GradientDrawable g = new GradientDrawable();
            g.setShape(GradientDrawable.OVAL);
            int col = Ui.SURFACE;
            try { if (!t.isNull("color")) col = Color.parseColor(t.optString("color")); } catch (Exception ignored) { }
            g.setColor(col);
            g.setStroke(Ui.dp(c, 1), Ui.LINE);
            sw.setBackground(g);
            r.addView(sw, new LinearLayout.LayoutParams(Ui.dp(c, 22), Ui.dp(c, 22)));
            boolean empty = t.optBoolean("empty");
            String name = empty ? "Empty" : (t.optString("type") + (t.optString("name").isEmpty() ? "" : " · " + t.optString("name")));
            TextView nm = Ui.text(c, "Slot " + t.optInt("tray") + "   " + name, 14, empty ? Ui.MUTED : Ui.TEXT, false);
            nm.setPadding(Ui.dp(c, 10), 0, 0, 0);
            r.addView(nm, Ui.weight(1));
            String right = t.optBoolean("active") ? "LOADED" : (t.isNull("remain") || t.optInt("remain") < 0 ? "" : t.optInt("remain") + "%");
            TextView rm = mono(right);
            rm.setTextColor(t.optBoolean("active") ? Ui.ACCENT : Ui.MUTED);
            r.addView(rm);
            r.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { slotMenu(t, busy); }
            });
            amsList.addView(r, lp);
        }
        final JSONObject ext = a.optJSONObject("external");
        LinearLayout er = Ui.row(c);
        er.setPadding(Ui.dp(c, 10), Ui.dp(c, 8), Ui.dp(c, 10), Ui.dp(c, 8));
        er.setBackground(Ui.box(c, Ui.SURFACE2, ext != null && ext.optBoolean("active") ? Ui.ACCENT : 0, 10));
        TextView et = Ui.text(c, "External spool   " + (ext == null || ext.optString("type").isEmpty() ? "not set" : ext.optString("type")), 14, Ui.TEXT, false);
        er.addView(et, Ui.weight(1));
        er.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            try {
                JSONObject t = new JSONObject().put("slot", 254).put("empty", false)
                        .put("type", ext == null ? "PLA" : ext.optString("type", "PLA"))
                        .put("color", ext == null || ext.isNull("color") ? "#FFFFFF" : ext.optString("color"));
                slotMenu(t, busy);
            } catch (Exception ignored) { }
        } });
        LinearLayout.LayoutParams elp = new LinearLayout.LayoutParams(-1, -2);
        elp.topMargin = Ui.dp(c, 8);
        amsList.addView(er, elp);
    }

    // ------------------------------------------------------------------ AMS slot actions
    private void slotMenu(final JSONObject t, final boolean busy) {
        final boolean empty = t.optBoolean("empty"), active = t.optBoolean("active");
        final int slot = t.optInt("slot");
        java.util.List<String> items = new java.util.ArrayList<>();
        final java.util.List<Runnable> acts = new java.util.ArrayList<>();
        if (!empty && !active && slot != 254) {
            items.add("Load this filament");
            acts.add(new Runnable() { public void run() {
                confirm("Load slot " + t.optInt("tray") + "?",
                        t.optString("type") + (busy ? "\n\nA print is running. Changing filament now changes the print's material." : ""),
                        "Load", new Runnable() { public void run() {
                            send("{\"action\":\"ams_load\",\"tray\":" + slot + "}", "Loading...");
                        } });
            } });
        }
        items.add("Set filament type & color");
        acts.add(new Runnable() { public void run() { editSlot(t); } });
        items.add("Pressure advance (K)" + (t.isNull("k") || t.optDouble("k", -1) < 0 ? "" : String.format(java.util.Locale.US, "  \u00B7  %.3f", t.optDouble("k"))));
        acts.add(new Runnable() { public void run() { PaDialog.show(ControlsActivity.this, t, null); } });
        if (slot != 254) {
            items.add("Re-read RFID tag");
            acts.add(new Runnable() { public void run() {
                send("{\"action\":\"ams_rfid\",\"slot\":" + slot + "}", "Reading tag...");
            } });
        }
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(slot == 254 ? "External spool" : "AMS " + t.optInt("unit") + " \u00B7 slot " + t.optInt("tray"))
                .setItems(items.toArray(new String[0]), new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) { acts.get(w).run(); }
                }).show();
    }

    // Generated from tools/filaments.txt: family, name, type sent to printer, nozzle min, max, Bambu generic profile
    static final String[][] FILAMENTS = {
            {"PLA", "PLA", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA+ / PLA Pro", "PLA", "200", "230", "GFL99"},
            {"PLA", "PLA Matte", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Silk", "PLA", "200", "230", "GFL96"},
            {"PLA", "PLA Silk Dual/Tri Color", "PLA", "200", "230", "GFL96"},
            {"PLA", "PLA High Speed", "PLA", "190", "230", "GFL95"},
            {"PLA", "PLA Tough", "PLA", "200", "230", "GFL99"},
            {"PLA", "PLA Translucent", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Glow in the Dark", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Sparkle / Galaxy", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Marble", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Wood", "PLA", "190", "220", "GFL99"},
            {"PLA", "PLA Metal Fill", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Stone / Ceramic Fill", "PLA", "190", "230", "GFL99"},
            {"PLA", "PLA Color Change (Thermo/UV)", "PLA", "190", "220", "GFL99"},
            {"PLA", "PLA Heat Resistant (HTPLA)", "PLA", "200", "230", "GFL99"},
            {"PLA", "PLA Lightweight / Aero (LW-PLA)", "PLA-AERO", "210", "260", "GFL99"},
            {"PLA", "PLA-CF (Carbon Fiber)", "PLA-CF", "210", "240", "GFL98"},
            {"PLA", "PLA-GF (Glass Fiber)", "PLA-CF", "210", "240", "GFL98"},
            {"PLA", "Support for PLA", "PLA-S", "190", "230", "GFL99"},
            {"PETG", "PETG", "PETG", "220", "260", "GFG99"},
            {"PETG", "PETG HF (High Flow)", "PETG", "230", "260", "GFG99"},
            {"PETG", "PETG Translucent", "PETG", "220", "260", "GFG99"},
            {"PETG", "PETG Matte", "PETG", "220", "260", "GFG99"},
            {"PETG", "PETG-CF (Carbon Fiber)", "PETG-CF", "240", "270", "GFG98"},
            {"PETG", "PETG-GF (Glass Fiber)", "PETG-CF", "240", "270", "GFG98"},
            {"PETG", "CPE / Co-polyester", "PETG", "240", "260", "GFG99"},
            {"PETG", "PCTG", "PCTG", "240", "270", "GFG99"},
            {"PETG", "PET-CF", "PET-CF", "260", "290", "GFG98"},
            {"PETG", "rPETG (Recycled)", "PETG", "220", "250", "GFG99"},
            {"ABS / ASA", "ABS", "ABS", "240", "270", "GFB99"},
            {"ABS / ASA", "ABS-GF (Glass Fiber)", "ABS-GF", "240", "270", "GFB99"},
            {"ABS / ASA", "ABS-CF (Carbon Fiber)", "ABS", "240", "270", "GFB99"},
            {"ABS / ASA", "ASA", "ASA", "240", "270", "GFB98"},
            {"ABS / ASA", "ASA-CF (Carbon Fiber)", "ASA-CF", "250", "280", "GFB98"},
            {"ABS / ASA", "ASA Aero (Lightweight)", "ASA-AERO", "240", "280", "GFB98"},
            {"ABS / ASA", "HIPS", "HIPS", "230", "260", "GFS98"},
            {"ABS / ASA", "PC-ABS", "PC", "250", "280", "GFC99"},
            {"PC", "PC (Polycarbonate)", "PC", "260", "290", "GFC99"},
            {"PC", "PC-CF (Carbon Fiber)", "PC", "260", "290", "GFC99"},
            {"PC", "PC-FR (Flame Retardant)", "PC", "260", "290", "GFC99"},
            {"Nylon", "PA (Nylon)", "PA", "260", "290", "GFN99"},
            {"Nylon", "PA6", "PA", "260", "290", "GFN99"},
            {"Nylon", "PA12", "PA", "250", "280", "GFN99"},
            {"Nylon", "PA-CF (Nylon Carbon Fiber)", "PA-CF", "260", "290", "GFN98"},
            {"Nylon", "PA6-CF", "PA6-CF", "260", "290", "GFN98"},
            {"Nylon", "PA12-CF", "PA-CF", "260", "290", "GFN98"},
            {"Nylon", "PA-GF (Nylon Glass Fiber)", "PA-GF", "260", "290", "GFN98"},
            {"Nylon", "PA6-GF", "PA6-GF", "260", "290", "GFN98"},
            {"Nylon", "PAHT-CF", "PAHT-CF", "260", "290", "GFN98"},
            {"Nylon", "PPA-CF", "PPA-CF", "280", "300", "GFN98"},
            {"Nylon", "PPA-GF", "PPA-GF", "280", "300", "GFN98"},
            {"Flexible", "TPU 95A", "TPU", "200", "240", "GFU99"},
            {"Flexible", "TPU 90A", "TPU", "200", "230", "GFU99"},
            {"Flexible", "TPU 85A", "TPU", "200", "230", "GFU99"},
            {"Flexible", "TPU 68D (Firm)", "TPU", "210", "240", "GFU99"},
            {"Flexible", "TPU for AMS", "TPU", "220", "240", "GFU99"},
            {"Flexible", "TPE", "TPU", "200", "230", "GFU99"},
            {"Flexible", "TPC / Flex Co-polyester", "TPU", "210", "240", "GFU99"},
            {"Flexible", "SBS", "SBS", "230", "250", "GFG99"},
            {"Engineering", "PP (Polypropylene)", "PP", "220", "250", ""},
            {"Engineering", "PP-CF", "PP-CF", "230", "260", ""},
            {"Engineering", "PP-GF", "PP-GF", "230", "260", ""},
            {"Engineering", "PE (Polyethylene)", "PE", "230", "260", ""},
            {"Engineering", "PE-CF", "PE-CF", "240", "270", ""},
            {"Engineering", "EVA", "EVA", "190", "220", ""},
            {"Engineering", "PHA", "PHA", "190", "220", "GFL99"},
            {"Engineering", "PVB (Polysmooth)", "PVB", "200", "230", ""},
            {"Engineering", "POM (Acetal)", "POM", "210", "240", ""},
            {"Engineering", "PMMA (Acrylic)", "PMMA", "240", "260", ""},
            {"Support", "PVA (Water Soluble)", "PVA", "190", "230", "GFS99"},
            {"Support", "BVOH (Water Soluble)", "BVOH", "210", "240", "GFS99"},
            {"Support", "HIPS (Limonene Soluble)", "HIPS", "230", "260", "GFS98"},
            {"Support", "Breakaway Support", "PLA-S", "200", "230", "GFL99"}
    };
    private static final String[] COLORS = {"#FFFFFF", "#161616", "#8C9098", "#FF3B30", "#FF9500", "#F5A524",
            "#FFD60A", "#34C759", "#30B0C7", "#007AFF", "#5856D6", "#AF52DE", "#FF2D55", "#A2845E", "#F5E6C8", "#004D40"};

    private void editSlot(final JSONObject t) {
        final Context c = this;
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 20);
        box.setPadding(p, Ui.dp(c, 8), p, 0);
        final String curType = t.optString("type", "").trim();
        final int[] type = {curType.isEmpty() ? 0 : -1};
        for (int i = FILAMENTS.length - 1; i >= 0; i--) if (FILAMENTS[i][2].equalsIgnoreCase(curType)) type[0] = i;
        final String[] color = {t.isNull("color") ? "#FFFFFF" : t.optString("color")};
        final EditText min = new EditText(c), max = new EditText(c), hex = new EditText(c);
        final EditText custom = new EditText(c);

        TextView ml = Ui.text(c, "Material", 13, Ui.MUTED, false);
        ml.setPadding(0, Ui.dp(c, 4), 0, Ui.dp(c, 4));
        box.addView(ml);
        final Button pick = Ui.button(c, "", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        pick.setTextSize(15);
        pick.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        pick.setPadding(Ui.dp(c, 14), 0, Ui.dp(c, 14), 0);
        box.addView(pick, new LinearLayout.LayoutParams(-1, Ui.dp(c, 50)));
        custom.setHint("Type name, e.g. PLA-LED");
        custom.setHintTextColor(Ui.FAINT);
        custom.setTextColor(Ui.TEXT);
        custom.setSingleLine(true);
        custom.setVisibility(View.GONE);
        if (type[0] < 0) custom.setText(curType);
        box.addView(custom);
        final Runnable showPick = new Runnable() { public void run() {
            boolean other = type[0] < 0;
            pick.setText(other ? "Other (type your own)  ▾" : FILAMENTS[type[0]][1] + "  ▾");
            custom.setVisibility(other ? View.VISIBLE : View.GONE);
        } };
        showPick.run();
        pick.setOnClickListener(new View.OnClickListener() { public void onClick(View v) {
            pickFilament(new PickDone() { public void picked(int idx) {
                type[0] = idx;
                if (idx >= 0) { min.setText(FILAMENTS[idx][3]); max.setText(FILAMENTS[idx][4]); }
                showPick.run();
            } });
        } });

        TextView cl = Ui.text(c, "Color", 13, Ui.MUTED, false);
        cl.setPadding(0, Ui.dp(c, 12), 0, Ui.dp(c, 4));
        box.addView(cl);
        LinearLayout cr = null;
        final View preview = new View(c);
        for (int i = 0; i < COLORS.length; i++) {
            if (i % 8 == 0) { cr = Ui.row(c); box.addView(cr); }
            final String col = COLORS[i];
            View sw = new View(c);
            GradientDrawable g = new GradientDrawable();
            g.setShape(GradientDrawable.OVAL);
            g.setColor(Color.parseColor(col));
            g.setStroke(Ui.dp(c, 1), Ui.LINE);
            sw.setBackground(g);
            sw.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { hex.setText(col); } });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(Ui.dp(c, 28), Ui.dp(c, 28));
            lp.setMargins(Ui.dp(c, 3), Ui.dp(c, 3), Ui.dp(c, 3), Ui.dp(c, 3));
            cr.addView(sw, lp);
        }
        LinearLayout hr = Ui.row(c);
        hex.setText(color[0]);
        hex.setTextColor(Ui.TEXT);
        hex.setTypeface(Ui.MONO);
        hex.setSingleLine(true);
        hr.addView(hex, Ui.weight(1));
        final GradientDrawable pg = new GradientDrawable();
        pg.setCornerRadius(Ui.dp(c, 8));
        pg.setStroke(Ui.dp(c, 1), Ui.LINE);
        preview.setBackground(pg);
        hr.addView(preview, new LinearLayout.LayoutParams(Ui.dp(c, 40), Ui.dp(c, 32)));
        box.addView(hr);
        hex.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int d) { }
            public void onTextChanged(CharSequence s, int a, int b, int d) { }
            public void afterTextChanged(android.text.Editable e) {
                try { pg.setColor(Color.parseColor(e.toString().trim())); } catch (Exception ignored) { }
            }
        });
        try { pg.setColor(Color.parseColor(color[0])); } catch (Exception ignored) { }

        LinearLayout temps = Ui.row(c);
        min.setInputType(InputType.TYPE_CLASS_NUMBER);
        max.setInputType(InputType.TYPE_CLASS_NUMBER);
        min.setTextColor(Ui.TEXT);
        max.setTextColor(Ui.TEXT);
        min.setText(type[0] >= 0 ? FILAMENTS[type[0]][3] : "200");
        max.setText(type[0] >= 0 ? FILAMENTS[type[0]][4] : "240");
        temps.addView(Ui.text(c, "Nozzle \u00B0C", 13, Ui.MUTED, false));
        temps.addView(min, Ui.weight(1));
        temps.addView(Ui.text(c, "to", 13, Ui.MUTED, false));
        temps.addView(max, Ui.weight(1));
        box.addView(temps);

        ScrollView sv = new ScrollView(c);
        sv.addView(box);
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(t.optInt("slot") == 254 ? "External spool" : "AMS slot " + t.optInt("tray"))
                .setView(sv)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        String ty, idx, name;
                        if (type[0] < 0) {
                            ty = custom.getText().toString().trim().toUpperCase();
                            if (ty.isEmpty()) { toast("Type a material name"); return; }
                            if (ty.length() > 16) ty = ty.substring(0, 16);
                            idx = ""; name = ty;
                        } else {
                            String[] f = FILAMENTS[type[0]];
                            ty = f[2]; idx = f[5]; name = f[1];
                        }
                        String h = hex.getText().toString().trim();
                        if (!h.startsWith("#")) h = "#" + h;
                        send("{\"action\":\"ams_setting\",\"slot\":" + t.optInt("slot") + ",\"type\":" + JSONObject.quote(ty)
                                + ",\"color\":" + JSONObject.quote(h) + ",\"min\":" + num(min, 190) + ",\"max\":" + num(max, 230)
                                + ",\"idx\":" + JSONObject.quote(idx) + "}", "Slot set to " + name);
                    }
                }).show();
    }

    interface PickDone { void picked(int idx); }

    /** Searchable list of every filament, grouped by family, plus "Other". */
    private void pickFilament(final PickDone done) {
        final Context c = this;
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(c, 16), Ui.dp(c, 8), Ui.dp(c, 16), 0);
        final EditText q = new EditText(c);
        q.setHint("Search, e.g. CF, silk, nylon");
        q.setHintTextColor(Ui.FAINT);
        q.setTextColor(Ui.TEXT);
        q.setSingleLine(true);
        box.addView(q);
        final LinearLayout list = new LinearLayout(c);
        list.setOrientation(LinearLayout.VERTICAL);
        ScrollView sv = new ScrollView(c);
        sv.addView(list);
        box.addView(sv, new LinearLayout.LayoutParams(-1, Ui.dp(c, 380)));
        final AlertDialog dlg = new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Choose material").setView(box).setNegativeButton("Cancel", null).create();
        final Runnable fill = new Runnable() { public void run() {
            list.removeAllViews();
            String f = q.getText().toString().trim().toLowerCase();
            String fam = null;
            for (int i = 0; i < FILAMENTS.length; i++) {
                final String[] r = FILAMENTS[i];
                if (!f.isEmpty() && !(r[0] + " " + r[1] + " " + r[2]).toLowerCase().contains(f)) continue;
                if (!r[0].equals(fam)) {
                    fam = r[0];
                    TextView h = Ui.heading(c, fam);
                    h.setPadding(0, Ui.dp(c, 14), 0, Ui.dp(c, 4));
                    list.addView(h);
                }
                final int idx = i;
                list.addView(pickRow(r[1], r[2] + " \u00B7 " + r[3] + "\u2013" + r[4] + "\u00B0C", new View.OnClickListener() {
                    public void onClick(View v) { dlg.dismiss(); done.picked(idx); }
                }));
            }
            TextView h = Ui.heading(c, "Anything else");
            h.setPadding(0, Ui.dp(c, 14), 0, Ui.dp(c, 4));
            list.addView(h);
            list.addView(pickRow("Other (type your own)", "Any name, you set the temperatures", new View.OnClickListener() {
                public void onClick(View v) { dlg.dismiss(); done.picked(-1); }
            }));
        } };
        q.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int d) { }
            public void onTextChanged(CharSequence s, int a, int b, int d) { }
            public void afterTextChanged(android.text.Editable e) { fill.run(); }
        });
        fill.run();
        dlg.show();
    }

    private View pickRow(String name, String sub, View.OnClickListener l) {
        Context c = this;
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setBackground(Ui.press(c, Ui.SURFACE2, 0, 12));
        row.setPadding(Ui.dp(c, 14), Ui.dp(c, 10), Ui.dp(c, 14), Ui.dp(c, 10));
        row.setClickable(true);
        row.setOnClickListener(l);
        row.addView(Ui.text(c, name, 15, Ui.TEXT, true));
        TextView s = Ui.text(c, sub, 12.5f, Ui.MUTED, false);
        s.setPadding(0, Ui.dp(c, 2), 0, 0);
        row.addView(s);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 6);
        row.setLayoutParams(lp);
        return row;
    }

    private static int num(EditText e, int def) {
        try { return Integer.parseInt(e.getText().toString().trim()); } catch (Exception x) { return def; }
    }

    private void setEnabledDeep(View v, boolean on) {
        v.setAlpha(on ? 1f : 0.4f);
        enableAll(v, on);
    }

    private void enableAll(View v, boolean on) {
        v.setEnabled(on);
        if (v instanceof LinearLayout) {
            LinearLayout l = (LinearLayout) v;
            for (int i = 0; i < l.getChildCount(); i++) enableAll(l.getChildAt(i), on);
        }
    }
}
