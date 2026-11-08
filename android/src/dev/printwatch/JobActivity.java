package dev.printwatch;

import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** The running job: plate preview and skipping objects. */
public class JobActivity extends Base {
    private ImageView img;
    private TextView status, meta;
    private LinearLayout objs;
    private Button skipBtn;
    private final List<CheckBox> boxes = new ArrayList<>();
    private final List<Integer> ids = new ArrayList<>();
    private final List<String> names = new ArrayList<>();

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Context c = this;
        LinearLayout p = page("Live", "Current job");
        FrameLayout box = new FrameLayout(c);
        box.setBackground(Ui.box(c, Color.BLACK, Ui.LINE, 16));
        box.setClipToOutline(true);
        img = new ImageView(c);
        img.setScaleType(ImageView.ScaleType.FIT_CENTER);
        box.addView(img, new FrameLayout.LayoutParams(-1, Ui.dp(c, 260)));
        p.addView(box);
        meta = Ui.text(c, "", 13, Ui.MUTED, false);
        meta.setTypeface(Ui.MONO);
        meta.setPadding(0, Ui.dp(c, 8), 0, 0);
        p.addView(meta);
        status = note(p, "Looking for this job's file on the SD card...");

        LinearLayout card = Ui.card(c);
        card.addView(Ui.heading(c, "Skip objects"));
        objs = new LinearLayout(c);
        objs.setOrientation(LinearLayout.VERTICAL);
        card.addView(objs);
        skipBtn = Ui.button(c, "Skip selected", Ui.DANGER, Color.WHITE, 0);
        LinearLayout.LayoutParams sl = new LinearLayout.LayoutParams(-1, -2);
        sl.topMargin = Ui.dp(c, 12);
        card.addView(skipBtn, sl);
        skipBtn.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { skip(); } });
        TextView n = Ui.text(c, "The printer stops printing the selected objects and finishes the rest. This can't be undone.", 12, Ui.MUTED, false);
        n.setPadding(0, Ui.dp(c, 8), 0, 0);
        card.addView(n);
        p.addView(card);
        load();
    }

    private void load() {
        getJson("/api/job", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) { status.setText(e); return; }
                if (!v.optBoolean("found")) {
                    status.setText("No running job found on the SD card. Skip objects works for prints started from a sliced 3MF (from the app, Bambu Studio or OrcaSlicer over LAN).");
                    skipBtn.setEnabled(false);
                    skipBtn.setAlpha(0.35f);
                    return;
                }
                status.setVisibility(View.GONE);
                image("/api/job/plate.png?t=" + System.currentTimeMillis(), img);
                StringBuilder m = new StringBuilder(v.optString("path")).append("  ·  plate ").append(v.optInt("plate"));
                if (v.optInt("seconds") > 0) m.append("\n~").append(Ui.mins(v.optInt("seconds") / 60.0)).append(" total");
                meta.setText(m.toString());
                render(v.optJSONArray("objects"));
            }
        });
    }

    private void render(JSONArray a) {
        objs.removeAllViews();
        boxes.clear(); ids.clear(); names.clear();
        int active = 0;
        for (int i = 0; a != null && i < a.length(); i++) {
            JSONObject o = a.optJSONObject(i);
            CheckBox cb = new CheckBox(this);
            boolean skipped = o.optBoolean("skipped");
            cb.setText(o.optString("name") + (skipped ? "   (skipped)" : ""));
            cb.setTextColor(skipped ? Ui.FAINT : Ui.TEXT);
            cb.setTextSize(15);
            cb.setEnabled(!skipped);
            cb.setPadding(Ui.dp(this, 6), Ui.dp(this, 8), 0, Ui.dp(this, 8));
            objs.addView(cb);
            if (!skipped) { boxes.add(cb); ids.add(o.optInt("id")); names.add(o.optString("name")); active++; }
        }
        if (a == null || a.length() == 0) note(objs, "This plate has no object list (single object or older slicer).");
        skipBtn.setEnabled(active > 1);
        skipBtn.setAlpha(active > 1 ? 1f : 0.35f);
    }

    private void skip() {
        final List<Integer> sel = new ArrayList<>();
        StringBuilder nm = new StringBuilder();
        for (int i = 0; i < boxes.size(); i++)
            if (boxes.get(i).isChecked()) { sel.add(ids.get(i)); nm.append("\n• ").append(names.get(i)); }
        if (sel.isEmpty()) { toast("Tick the objects to skip"); return; }
        if (sel.size() == boxes.size()) { toast("That's every object. Use Stop instead."); return; }
        confirm("Skip " + sel.size() + " object" + (sel.size() == 1 ? "" : "s") + "?", nm.toString().trim(), "Skip", new Runnable() {
            public void run() {
                StringBuilder j = new StringBuilder("{\"action\":\"skip\",\"objects\":[");
                for (int i = 0; i < sel.size(); i++) j.append(i > 0 ? "," : "").append(sel.get(i));
                j.append("]}");
                post("/api/cmd", j.toString(), new Done<JSONObject>() {
                    public void run(JSONObject v, String e) {
                        toast(e == null ? "Skipped" : e);
                        ui.postDelayed(new Runnable() { public void run() { load(); } }, 2500);
                    }
                });
            }
        });
    }
}
