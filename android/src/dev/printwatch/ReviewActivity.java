package dev.printwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Scrub through one recorded print and label it. */
public class ReviewActivity extends Activity {
    @Override protected void onPause() { if (pip != null) { pip.hide(); pip = null; } super.onPause(); }
    @Override protected void onResume() { super.onResume(); pip = CamPip.show(this); }
    private CamPip pip;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newSingleThreadExecutor();
    private String id;
    private JSONObject meta;
    private JSONArray ticks = new JSONArray();
    private int idx;
    private int wanted = -1;
    private boolean loading;

    private ImageView img;
    private TextView title, ts, lab, info;
    private SeekBar seek;
    private Chart chart;
    private Button fail, good, ignore, delete;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(Ui.BG);
        getWindow().setNavigationBarColor(Ui.BG);
        id = getIntent().getStringExtra("id");
        setContentView(build());
        load();
    }

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
        Button back = new Button(c);
        back.setText("‹ Prints");
        back.setAllCaps(false);
        back.setTextColor(Ui.MUTED);
        back.setBackgroundColor(Color.TRANSPARENT);
        back.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { finish(); } });
        head.addView(back);
        title = Ui.text(c, "Print", 17, Ui.TEXT, true);
        title.setSingleLine(true);
        head.addView(title, Ui.weight(1));
        root.addView(head);

        FrameLayout box = new FrameLayout(c) {
            @Override
            protected void onMeasure(int w, int h) {
                int width = MeasureSpec.getSize(w);
                super.onMeasure(w, MeasureSpec.makeMeasureSpec(width * 9 / 16, MeasureSpec.EXACTLY));
            }
        };
        box.setBackground(Ui.box(c, Color.BLACK, Ui.LINE, 16));
        box.setClipToOutline(true);
        img = new ImageView(c);
        img.setScaleType(ImageView.ScaleType.FIT_CENTER);
        box.addView(img, new FrameLayout.LayoutParams(-1, -1));
        ts = Ui.text(c, "", 12, Ui.TEXT, false);
        ts.setTypeface(Ui.MONO);
        ts.setBackground(Ui.box(c, Color.parseColor("#bf0e0f11"), 0, 8));
        ts.setPadding(Ui.dp(c, 8), Ui.dp(c, 4), Ui.dp(c, 8), Ui.dp(c, 4));
        FrameLayout.LayoutParams tl = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.START);
        tl.setMargins(Ui.dp(c, 10), Ui.dp(c, 10), 0, 0);
        box.addView(ts, tl);
        lab = Ui.text(c, "", 11, Ui.TEXT, true);
        lab.setPadding(Ui.dp(c, 8), Ui.dp(c, 4), Ui.dp(c, 8), Ui.dp(c, 4));
        FrameLayout.LayoutParams ll = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.END);
        ll.setMargins(0, Ui.dp(c, 10), Ui.dp(c, 10), 0);
        box.addView(lab, ll);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(-1, -2);
        blp.topMargin = Ui.dp(c, 6);
        root.addView(box, blp);

        seek = new SeekBar(c);
        seek.setPadding(Ui.dp(c, 12), Ui.dp(c, 16), Ui.dp(c, 12), Ui.dp(c, 16));
        seek.setProgressTintList(android.content.res.ColorStateList.valueOf(Ui.ACCENT));
        seek.setThumbTintList(android.content.res.ColorStateList.valueOf(Ui.ACCENT));
        root.addView(seek);
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar s, int v, boolean user) { if (user) { idx = v; show(); } }
            public void onStartTrackingTouch(SeekBar s) { }
            public void onStopTrackingTouch(SeekBar s) { }
        });

        LinearLayout steps = Ui.row(c);
        String[] st = {"-5m", "‹", "›", "+5m"};
        final int[] delta = {-30, -1, 1, 30};
        for (int i = 0; i < 4; i++) {
            final int d = delta[i];
            Button b = Ui.button(c, st[i], Ui.SURFACE2, Ui.TEXT, Ui.LINE);
            b.setMinHeight(Ui.dp(c, 46));
            b.setTextSize(15);
            b.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { idx += d; show(); } });
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 8);
            steps.addView(b, lp);
        }
        root.addView(steps);

        chart = new Chart(c);
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(-1, Ui.dp(c, 60));
        clp.topMargin = Ui.dp(c, 12);
        root.addView(chart, clp);
        TextView legend = Ui.text(c, "▬ Obico   ▬ Your model   ■ Marked failure", 12, Ui.MUTED, false);
        legend.setPadding(0, Ui.dp(c, 6), 0, 0);
        root.addView(legend);

        info = Ui.text(c, "Loading...", 13, Ui.MUTED, false);
        info.setPadding(0, Ui.dp(c, 10), 0, 0);
        root.addView(info);

        fail = Ui.button(c, "Failure started here", Ui.DANGER, Color.WHITE, 0);
        good = Ui.button(c, "Whole print was fine", Ui.OK, Color.parseColor("#111111"), 0);
        ignore = Ui.button(c, "Ignore print", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        delete = Ui.button(c, "Delete", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        LinearLayout.LayoutParams f = new LinearLayout.LayoutParams(-1, -2);
        f.topMargin = Ui.dp(c, 14);
        root.addView(fail, f);
        LinearLayout.LayoutParams g = new LinearLayout.LayoutParams(-1, -2);
        g.topMargin = Ui.dp(c, 8);
        root.addView(good, g);
        LinearLayout two = Ui.row(c);
        LinearLayout.LayoutParams il = Ui.weight(1);
        il.rightMargin = Ui.dp(c, 8);
        two.addView(ignore, il);
        two.addView(delete, Ui.weight(1));
        LinearLayout.LayoutParams tw = new LinearLayout.LayoutParams(-1, -2);
        tw.topMargin = Ui.dp(c, 8);
        root.addView(two, tw);

        fail.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { label("{\"label\":\"failed\",\"fail_start\":" + idx + "}", "Marked failure from here"); }
        });
        good.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { label("{\"label\":\"good\"}", "Marked good"); }
        });
        ignore.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { label("{\"label\":\"ignore\"}", "Ignored"); }
        });
        delete.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                new AlertDialog.Builder(ReviewActivity.this, android.R.style.Theme_Material_Dialog_Alert)
                        .setTitle("Delete this recording?")
                        .setMessage("Its frames and features are removed from the Pi.")
                        .setNegativeButton("Cancel", null)
                        .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                            public void onClick(DialogInterface d, int w) { send("/api/prints/" + id + "/delete", "{}", "Deleted"); }
                        }).show();
            }
        });
        return sv;
    }

    private void load() {
        net.execute(new Runnable() {
            public void run() {
                try {
                    final JSONObject d = new JSONObject(Api.get(ReviewActivity.this, "/api/prints/" + id, null, 10000).text());
                    ui.post(new Runnable() {
                        public void run() {
                            meta = d.optJSONObject("meta");
                            ticks = d.optJSONArray("ticks");
                            if (ticks == null) ticks = new JSONArray();
                            start();
                        }
                    });
                } catch (Exception e) {
                    ui.post(new Runnable() { public void run() { info.setText("Can't load this print."); } });
                }
            }
        });
    }

    private void start() {
        title.setText(meta.optString("job", "Print"));
        int n = Math.max(1, ticks.length());
        seek.setMax(n - 1);
        if ("failed".equals(meta.optString("label"))) idx = meta.optInt("fail_start");
        else if (meta.optBoolean("flagged")) idx = highest();
        else idx = n / 2;
        boolean rec = "recording".equals(meta.optString("status"));
        boolean pruned = meta.optBoolean("frames_pruned");
        enable(fail, !rec && !pruned);
        enable(good, !rec);
        enable(ignore, !rec);
        enable(delete, !rec);
        info.setText(rec ? "Still recording. Label it when it ends."
                : pruned ? "Old frames were pruned to save space; features are kept, so it still trains."
                : ticks.length() + " frames, one every 10 s. Ended: " + meta.optString("end_state", "").toLowerCase()
                + (meta.optBoolean("flagged") ? " (detector flagged it)" : "") + ".");
        show();
    }

    private void enable(Button b, boolean on) {
        b.setEnabled(on);
        b.setAlpha(on ? 1f : 0.35f);
    }

    private int highest() {
        double best = 0;
        int bi = ticks.length() / 2;
        for (int i = 0; i < ticks.length(); i++) {
            JSONObject t = ticks.optJSONObject(i);
            double v = Math.max(t.optDouble("po", 0), t.isNull("pc") ? 0 : t.optDouble("pc", 0));
            if (v > best) { best = v; bi = i; }
        }
        return bi;
    }

    private void show() {
        if (ticks.length() == 0) return;
        idx = Math.max(0, Math.min(ticks.length() - 1, idx));
        seek.setProgress(idx);
        JSONObject t = ticks.optJSONObject(idx);
        double secs = t.optDouble("t") - meta.optDouble("started");
        ts.setText(Ui.mins(secs / 60.0) + " in · " + (idx + 1) + "/" + ticks.length());
        String l = meta.optString("label", "");
        String txt = "failed".equals(l) ? (idx >= meta.optInt("fail_start") ? "FAILURE" : "FINE")
                : "good".equals(l) ? "FINE" : "ignore".equals(l) ? "IGNORED" : "";
        lab.setText(txt);
        lab.setVisibility(txt.isEmpty() ? View.GONE : View.VISIBLE);
        lab.setTextColor(txt.equals("FAILURE") ? Ui.DANGER : txt.equals("FINE") ? Ui.OK : Ui.MUTED);
        lab.setBackground(Ui.box(this, Color.parseColor("#bf0e0f11"), 0, 99));
        chart.invalidate();
        if (!meta.optBoolean("frames_pruned")) fetchFrame(idx);
    }

    /** Only the newest requested frame loads; fast scrubbing skips the rest. */
    private void fetchFrame(int i) {
        wanted = i;
        if (loading) return;
        loading = true;
        final int want = i;
        net.execute(new Runnable() {
            public void run() {
                Bitmap bm = null;
                try {
                    Api.Resp r = Api.get(ReviewActivity.this, "/api/prints/" + id + "/frame/" + want, null, 10000);
                    if (r.code == 200 && r.body != null) bm = BitmapFactory.decodeByteArray(r.body, 0, r.body.length);
                } catch (Exception ignored) { }
                final Bitmap fb = bm;
                ui.post(new Runnable() {
                    public void run() {
                        loading = false;
                        if (fb != null) img.setImageBitmap(fb);
                        if (wanted != want) fetchFrame(wanted);
                    }
                });
            }
        });
    }

    private void label(String json, String msg) {
        send("/api/prints/" + id + "/label", json, msg);
    }

    private void send(final String path, final String json, final String msg) {
        net.execute(new Runnable() {
            public void run() {
                String err = null;
                try {
                    Api.Resp r = Api.post(ReviewActivity.this, path, json);
                    if (r.code != 200) err = new JSONObject(r.text()).optString("error", "HTTP " + r.code);
                } catch (Exception e) { err = "Can't reach PrintWatch"; }
                final String fe = err;
                ui.post(new Runnable() {
                    public void run() {
                        Toast.makeText(ReviewActivity.this, fe == null ? msg : fe, Toast.LENGTH_SHORT).show();
                        if (fe == null) finish();
                    }
                });
            }
        });
    }

    /** Obico (amber) and your model (blue) scores over the print; tap/drag to seek. */
    private class Chart extends View {
        private final Paint pa = new Paint(Paint.ANTI_ALIAS_FLAG), pb = new Paint(Paint.ANTI_ALIAS_FLAG),
                bg = new Paint(), fl = new Paint(), cur = new Paint();

        Chart(Context c) {
            super(c);
            pa.setColor(Ui.ACCENT); pa.setStrokeWidth(Ui.dp(c, 1.5f)); pa.setStyle(Paint.Style.STROKE);
            pb.setColor(Ui.INFO); pb.setStrokeWidth(Ui.dp(c, 1.5f)); pb.setStyle(Paint.Style.STROKE);
            bg.setColor(Ui.SURFACE2);
            fl.setColor(Color.parseColor("#2eff5a4e"));
            cur.setColor(Ui.TEXT);
        }

        @Override
        protected void onDraw(Canvas cv) {
            int w = getWidth(), h = getHeight(), n = ticks.length();
            cv.drawRoundRect(0, 0, w, h, Ui.dp(getContext(), 10), Ui.dp(getContext(), 10), bg);
            if (n < 2 || meta == null) return;
            if ("failed".equals(meta.optString("label"))) cv.drawRect(x(meta.optInt("fail_start"), n, w), 0, w, h, fl);
            double maxPo = 1.5;
            for (int i = 0; i < n; i++) maxPo = Math.max(maxPo, ticks.optJSONObject(i).optDouble("po", 0));
            line(cv, "po", maxPo, pa, n, w, h);
            line(cv, "pc", 1.0, pb, n, w, h);
            float cx = x(idx, n, w);
            cv.drawRect(cx - 2, 0, cx + 2, h, cur);
        }

        private float x(int i, int n, int w) { return (float) i / (n - 1) * w; }

        private void line(Canvas cv, String key, double scale, Paint p, int n, int w, int h) {
            float px = 0, py = 0;
            boolean have = false;
            for (int i = 0; i < n; i++) {
                JSONObject t = ticks.optJSONObject(i);
                if (t.isNull(key)) { have = false; continue; }
                float x = x(i, n, w), y = (float) (h - 4 - Math.min(t.optDouble(key, 0), scale) / scale * (h - 8));
                if (have) cv.drawLine(px, py, x, y, p);
                px = x; py = y; have = true;
            }
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            if (ticks.length() < 2) return true;
            getParent().requestDisallowInterceptTouchEvent(true);
            idx = Math.round(e.getX() / getWidth() * (ticks.length() - 1));
            show();
            return true;
        }
    }
}
