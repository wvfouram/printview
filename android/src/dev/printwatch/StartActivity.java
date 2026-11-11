package dev.printwatch;

import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Pick plate, map filaments to AMS slots, choose options, start the print. */
public class StartActivity extends Base {
    private String path;
    private JSONArray plates;
    private JSONObject plate;
    private JSONArray trays = new JSONArray();
    private JSONObject external;
    private LinearLayout plateRow, filBox, body;
    private ImageView img;
    private TextView meta, status;
    private Switch useAms, timelapse, level, flow, vib;
    private final List<int[]> mapping = new ArrayList<>();   // {filamentId, slot}
    private final List<TextView> mapLabels = new ArrayList<>();

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        path = getIntent().getStringExtra("path");
        LinearLayout p = page("Files", getIntent().getStringExtra("title"));
        status = note(p, "Reading the file from the SD card...");
        body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setVisibility(View.GONE);
        p.addView(body);
        build(body);
        getJson("/api/status", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (v == null) return;
                JSONObject ams = v.optJSONObject("printer") == null ? null : v.optJSONObject("printer").optJSONObject("ams");
                if (ams != null) {
                    trays = ams.optJSONArray("trays") == null ? new JSONArray() : ams.optJSONArray("trays");
                    external = ams.optJSONObject("external");
                }
                getJson("/api/files/info?path=" + q(path), new Done<JSONObject>() {
                    public void run(JSONObject v2, String e2) {
                        if (e2 != null) { status.setText(e2); return; }
                        plates = v2.optJSONArray("plates");
                        showPlates();
                    }
                });
            }
        });
    }

    private void build(LinearLayout p) {
        Context c = this;
        plateRow = Ui.row(c);
        p.addView(plateRow);
        FrameLayout box = new FrameLayout(c);
        box.setBackground(Ui.box(c, Color.BLACK, Ui.LINE, 16));
        box.setClipToOutline(true);
        img = new ImageView(c);
        img.setScaleType(ImageView.ScaleType.FIT_CENTER);
        box.addView(img, new FrameLayout.LayoutParams(-1, Ui.dp(c, 240)));
        Button v3 = Ui.button(c, "3D view", Ui.ACCENT, Color.parseColor("#111111"), 0);
        v3.setTextSize(13);
        v3.setMinHeight(Ui.dp(c, 38));
        v3.setPadding(Ui.dp(c, 16), 0, Ui.dp(c, 16), 0);
        FrameLayout.LayoutParams vl = new FrameLayout.LayoutParams(-2, Ui.dp(c, 38), android.view.Gravity.BOTTOM | android.view.Gravity.END);
        vl.setMargins(0, 0, Ui.dp(c, 10), Ui.dp(c, 10));
        box.addView(v3, vl);
        View.OnClickListener open3d = new View.OnClickListener() {
            public void onClick(View v) {
                if (plate == null) return;
                startActivity(new android.content.Intent(StartActivity.this, Viewer3DActivity.class)
                        .putExtra("path", path).putExtra("plate", plate.optInt("index"))
                        .putExtra("title", getIntent().getStringExtra("title")));
            }
        };
        v3.setOnClickListener(open3d);
        img.setOnClickListener(open3d);
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-1, -2);
        bl.topMargin = Ui.dp(c, 10);
        p.addView(box, bl);
        meta = Ui.text(c, "", 13, Ui.MUTED, false);
        meta.setTypeface(Ui.MONO);
        meta.setPadding(0, Ui.dp(c, 8), 0, 0);
        p.addView(meta);

        LinearLayout fc = Ui.card(c);
        fc.addView(Ui.heading(c, "Filament → AMS slot"));
        useAms = sw(fc, "Use AMS", "Off = print from the external spool", true);
        useAms.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton b, boolean on) { filBox.setAlpha(on ? 1f : 0.4f); }
        });
        filBox = new LinearLayout(c);
        filBox.setOrientation(LinearLayout.VERTICAL);
        fc.addView(filBox);
        p.addView(fc);

        LinearLayout oc = Ui.card(c);
        oc.addView(Ui.heading(c, "Options"));
        timelapse = sw(oc, "Timelapse", "Saved to the SD card when the print ends", false);
        level = sw(oc, "Bed leveling", "Auto bed leveling before the print", true);
        flow = new Switch(this); flow.setChecked(false);   // P1S has no automatic K calibration
        vib = sw(oc, "Vibration calibration", "Resonance compensation before the print", true);
        p.addView(oc);

        Button go = Ui.button(c, "Start print", Ui.ACCENT, Color.parseColor("#111111"), 0);
        LinearLayout.LayoutParams gl = new LinearLayout.LayoutParams(-1, -2);
        gl.topMargin = Ui.dp(c, 14);
        p.addView(go, gl);
        go.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { start(); } });
        Button sch = Ui.button(c, "Schedule for later", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        LinearLayout.LayoutParams sl = new LinearLayout.LayoutParams(-1, -2);
        sl.topMargin = Ui.dp(c, 8);
        p.addView(sch, sl);
        sch.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { pickTime(); } });
        note(p, "Check the build plate is clear before starting.");
    }

    private Switch sw(LinearLayout parent, String title, String sub, boolean on) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setPadding(0, Ui.dp(c, 12), 0, 0);
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        t.addView(Ui.text(c, title, 15, Ui.TEXT, true));
        t.addView(Ui.text(c, sub, 12, Ui.MUTED, false));
        r.addView(t, Ui.weight(1));
        Switch s = new Switch(c);
        s.setChecked(on);
        r.addView(s);
        parent.addView(r);
        return s;
    }

    private void showPlates() {
        List<JSONObject> sliced = new ArrayList<>();
        for (int i = 0; plates != null && i < plates.length(); i++)
            if (plates.optJSONObject(i).optBoolean("sliced")) sliced.add(plates.optJSONObject(i));
        if (sliced.isEmpty()) { status.setText("This file has no sliced plates. Slice it in Bambu Studio and send it again."); return; }
        status.setVisibility(View.GONE);
        body.setVisibility(View.VISIBLE);
        plateRow.removeAllViews();
        if (sliced.size() > 1) {
            for (final JSONObject pl : sliced) {
                Button b = Ui.button(this, "Plate " + pl.optInt("index"), Ui.SURFACE2, Ui.TEXT, 0);
                b.setTextSize(13);
                b.setMinHeight(Ui.dp(this, 40));
                b.setTag(pl.optInt("index"));
                b.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { select(pl); } });
                LinearLayout.LayoutParams lp = Ui.weight(1);
                if (plateRow.getChildCount() > 0) lp.leftMargin = Ui.dp(this, 6);
                plateRow.addView(b, lp);
            }
        }
        select(sliced.get(0));
    }

    private void select(JSONObject pl) {
        plate = pl;
        for (int i = 0; i < plateRow.getChildCount(); i++) {
            View v = plateRow.getChildAt(i);
            boolean on = ((Integer) v.getTag()) == pl.optInt("index");
            v.setBackground(Ui.box(this, on ? Ui.ACCENT : Ui.SURFACE2, 0, 12));
            ((Button) v).setTextColor(on ? Color.parseColor("#111111") : Ui.TEXT);
        }
        img.setImageDrawable(null);
        if (pl.optBoolean("thumb")) image("/api/files/plate.png?path=" + q(path) + "&plate=" + pl.optInt("index"), img);
        int s = pl.optInt("seconds");
        StringBuilder m = new StringBuilder();
        if (s > 0) m.append("~").append(Ui.mins(s / 60.0));
        if (!pl.isNull("weight_g")) m.append(m.length() > 0 ? " · " : "").append(Math.round(pl.optDouble("weight_g"))).append(" g");
        JSONArray objs = pl.optJSONArray("objects");
        if (objs != null && objs.length() > 0) m.append(" · ").append(objs.length()).append(" object").append(objs.length() == 1 ? "" : "s");
        meta.setText(m.toString());
        buildMapping(pl.optJSONArray("filaments"));
    }

    /** Auto-match each filament to the AMS slot with the same type and closest color. */
    private void buildMapping(JSONArray fils) {
        filBox.removeAllViews();
        mapping.clear();
        mapLabels.clear();
        Context c = this;
        if (fils == null || fils.length() == 0) {
            mapping.add(new int[]{1, firstLoadedSlot()});
            fils = new JSONArray();
        }
        for (int i = 0; i < fils.length(); i++) {
            JSONObject f = fils.optJSONObject(i);
            int slot = bestSlot(f.optString("type"), f.optString("color"));
            mapping.add(new int[]{f.optInt("id", i + 1), slot});
        }
        for (int i = 0; i < mapping.size(); i++) {
            final int idx = i;
            JSONObject f = fils.optJSONObject(i);
            LinearLayout r = Ui.row(c);
            r.setPadding(0, Ui.dp(c, 10), 0, 0);
            r.addView(swatch(f == null ? null : f.optString("color")));
            String name = f == null ? "Filament 1" : f.optString("type") + (f.isNull("used_g") ? "" : "  " + Math.round(f.optDouble("used_g")) + " g");
            TextView t = Ui.text(c, name, 14, Ui.TEXT, false);
            t.setPadding(Ui.dp(c, 10), 0, 0, 0);
            r.addView(t, Ui.weight(1));
            TextView sel = Ui.text(c, "", 14, Ui.ACCENT, true);
            sel.setPadding(Ui.dp(c, 12), Ui.dp(c, 8), Ui.dp(c, 12), Ui.dp(c, 8));
            sel.setBackground(Ui.box(c, Ui.SURFACE2, Ui.LINE, 10));
            sel.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { pickSlot(idx); } });
            r.addView(sel);
            mapLabels.add(sel);
            filBox.addView(r);
        }
        paintMapping();
    }

    private View swatch(String color) {
        View v = new View(this);
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        int col = Ui.SURFACE2;
        try { if (color != null && color.startsWith("#")) col = Color.parseColor(color.substring(0, 7)); } catch (Exception ignored) { }
        g.setColor(col);
        g.setStroke(Ui.dp(this, 1), Ui.LINE);
        v.setBackground(g);
        v.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(this, 22), Ui.dp(this, 22)));
        return v;
    }

    private int firstLoadedSlot() {
        for (int i = 0; i < trays.length(); i++) if (!trays.optJSONObject(i).optBoolean("empty")) return trays.optJSONObject(i).optInt("slot");
        return 254;
    }

    private int bestSlot(String type, String color) {
        int best = -1;
        double bestD = Double.MAX_VALUE;
        for (int i = 0; i < trays.length(); i++) {
            JSONObject t = trays.optJSONObject(i);
            if (t.optBoolean("empty") || !type.equalsIgnoreCase(t.optString("type"))) continue;
            double d = colorDist(color, t.optString("color"));
            if (d < bestD) { bestD = d; best = t.optInt("slot"); }
        }
        return best >= 0 ? best : firstLoadedSlot();
    }

    private static double colorDist(String a, String b) {
        try {
            int x = Color.parseColor(a.substring(0, 7)), y = Color.parseColor(b.substring(0, 7));
            int dr = Color.red(x) - Color.red(y), dg = Color.green(x) - Color.green(y), db = Color.blue(x) - Color.blue(y);
            return dr * dr + dg * dg + db * db;
        } catch (Exception e) { return 1e9; }
    }

    private String slotName(int slot) {
        if (slot == 254) return "External";
        for (int i = 0; i < trays.length(); i++) {
            JSONObject t = trays.optJSONObject(i);
            if (t.optInt("slot") == slot) return "AMS " + t.optInt("unit") + " · " + t.optInt("tray") + "  " + t.optString("type");
        }
        return "Slot " + (slot + 1);
    }

    private void paintMapping() {
        for (int i = 0; i < mapping.size(); i++) mapLabels.get(i).setText(slotName(mapping.get(i)[1]) + "  ▾");
    }

    private void pickSlot(final int idx) {
        final List<Integer> slots = new ArrayList<>();
        List<String> names = new ArrayList<>();
        for (int i = 0; i < trays.length(); i++) {
            JSONObject t = trays.optJSONObject(i);
            if (t.optBoolean("empty")) continue;
            slots.add(t.optInt("slot"));
            names.add(slotName(t.optInt("slot")) + (t.isNull("remain") || t.optInt("remain") < 0 ? "" : "  (" + t.optInt("remain") + "%)"));
        }
        slots.add(254);
        names.add("External spool" + (external != null ? "  " + external.optString("type") : ""));
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Use which slot?")
                .setItems(names.toArray(new String[0]), new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int which) {
                        mapping.get(idx)[1] = slots.get(which);
                        paintMapping();
                    }
                }).show();
    }

    private void pickTime() {
        if (plate == null) return;
        final java.util.Calendar cal = java.util.Calendar.getInstance();
        new android.app.DatePickerDialog(this, android.R.style.Theme_Material_Dialog_Alert, new android.app.DatePickerDialog.OnDateSetListener() {
            public void onDateSet(android.widget.DatePicker d, int y, int m, int day) {
                cal.set(y, m, day);
                new android.app.TimePickerDialog(StartActivity.this, android.R.style.Theme_Material_Dialog_Alert, new android.app.TimePickerDialog.OnTimeSetListener() {
                    public void onTimeSet(android.widget.TimePicker t, int h, int min) {
                        cal.set(java.util.Calendar.HOUR_OF_DAY, h);
                        cal.set(java.util.Calendar.MINUTE, min);
                        cal.set(java.util.Calendar.SECOND, 0);
                        schedule(cal.getTimeInMillis() / 1000L);
                    }
                }, cal.get(java.util.Calendar.HOUR_OF_DAY), cal.get(java.util.Calendar.MINUTE), android.text.format.DateFormat.is24HourFormat(StartActivity.this)).show();
            }
        }, cal.get(java.util.Calendar.YEAR), cal.get(java.util.Calendar.MONTH), cal.get(java.util.Calendar.DAY_OF_MONTH)).show();
    }

    private void schedule(final long at) {
        final String json = body().replaceFirst("\\}$", ",\"at\":" + at + "}");
        String when = java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.MEDIUM, java.text.DateFormat.SHORT).format(new java.util.Date(at * 1000L));
        confirm("Schedule this print?", getIntent().getStringExtra("title") + "\nStarts " + when + "\nClear the plate before then.", "Schedule",
                new Runnable() {
                    public void run() {
                        post("/api/schedule", json, new Done<JSONObject>() {
                            public void run(JSONObject v, String e) {
                                toast(e == null ? "Scheduled" : e);
                                if (e == null) finish();
                            }
                        });
                    }
                });
    }

    private String body() {
        int maxId = 0;
        for (int[] m : mapping) maxId = Math.max(maxId, m[0]);
        int[] arr = new int[Math.max(1, maxId)];
        for (int i = 0; i < arr.length; i++) arr[i] = -1;
        boolean ext = false;
        for (int[] m : mapping) { arr[m[0] - 1] = m[1]; if (m[1] == 254) ext = true; }
        boolean ams = useAms.isChecked() && !ext;
        StringBuilder am = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) am.append(i > 0 ? "," : "").append(arr[i]);
        am.append("]");
        return "{\"path\":" + JSONObject.quote(path) + ",\"plate\":" + plate.optInt("index")
                + ",\"use_ams\":" + ams + ",\"ams_mapping\":" + (ams ? am.toString() : "[]")
                + ",\"timelapse\":" + timelapse.isChecked() + ",\"bed_leveling\":" + level.isChecked()
                + ",\"flow_cali\":false,\"vibration_cali\":" + vib.isChecked() + "}";
    }

    private void start() {
        if (plate == null) return;
        int maxId = 0;
        for (int[] m : mapping) maxId = Math.max(maxId, m[0]);
        int[] arr = new int[Math.max(1, maxId)];
        for (int i = 0; i < arr.length; i++) arr[i] = -1;
        boolean ext = false;
        for (int[] m : mapping) { arr[m[0] - 1] = m[1]; if (m[1] == 254) ext = true; }
        final boolean ams = useAms.isChecked() && !ext;
        StringBuilder am = new StringBuilder("[");
        for (int i = 0; i < arr.length; i++) am.append(i > 0 ? "," : "").append(arr[i]);
        am.append("]");
        final String json = "{\"path\":" + JSONObject.quote(path) + ",\"plate\":" + plate.optInt("index")
                + ",\"use_ams\":" + ams + ",\"ams_mapping\":" + (ams ? am.toString() : "[]")
                + ",\"timelapse\":" + timelapse.isChecked() + ",\"bed_leveling\":" + level.isChecked()
                + ",\"flow_cali\":" + flow.isChecked() + ",\"vibration_cali\":" + vib.isChecked() + "}";
        confirm("Start this print?", getIntent().getStringExtra("title") + "  ·  plate " + plate.optInt("index")
                        + (ams ? "" : "\nFrom the external spool."), "Start",
                new Runnable() {
                    public void run() {
                        post("/api/print", json, new Done<JSONObject>() {
                            public void run(JSONObject v, String e) {
                                toast(e == null ? "Print started" : e);
                                if (e == null) finish();
                            }
                        });
                    }
                });
    }
}
