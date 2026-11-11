package dev.printwatch;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Model stats + list of recorded prints to label. */
public class TrainActivity extends Activity {
    @Override protected void onPause() { if (pip != null) { pip.hide(); pip = null; } super.onPause(); }
    private CamPip pip;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newFixedThreadPool(3);
    private LinearLayout list;
    private TextView badge, body, mine, mineSub, obico, obicoSub, progressTxt, trainState;
    private LinearLayout cmp;
    private Switch useCustom;
    private Button trainBtn;
    private String filter = "review";
    private final Button[] tabs = new Button[4];
    private static final String[] FILTERS = {"review", "all", "failed", "good"};
    private boolean settingSwitch;

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
        loadModel();
        loadPrints();
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
        back.setText("‹ Live");
        back.setAllCaps(false);
        back.setTextColor(Ui.MUTED);
        back.setBackgroundColor(Color.TRANSPARENT);
        back.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { finish(); } });
        head.addView(back);
        head.addView(Ui.text(c, "Train detection", 18, Ui.TEXT, true));
        root.addView(head);

        // model card
        LinearLayout m = Ui.card(c);
        LinearLayout mh = Ui.row(c);
        mh.addView(Ui.heading(c, "Your model"), Ui.weight(1));
        badge = Ui.text(c, "-", 11, Ui.MUTED, true);
        badge.setPadding(Ui.dp(c, 8), Ui.dp(c, 3), Ui.dp(c, 8), Ui.dp(c, 3));
        mh.addView(badge);
        m.addView(mh);
        body = Ui.text(c, "", 13, Ui.MUTED, false);
        body.setPadding(0, Ui.dp(c, 8), 0, 0);
        m.addView(body);
        cmp = Ui.row(c);
        cmp.setPadding(0, Ui.dp(c, 12), 0, 0);
        TextView[] a = cmpBox(cmp, "YOUR MODEL", true);
        mine = a[0]; mineSub = a[1];
        TextView[] o = cmpBox(cmp, "OBICO STOCK", false);
        obico = o[0]; obicoSub = o[1];
        m.addView(cmp);
        progressTxt = Ui.text(c, "", 13, Ui.TEXT, false);
        progressTxt.setTypeface(Ui.MONO);
        progressTxt.setPadding(0, Ui.dp(c, 10), 0, 0);
        m.addView(progressTxt);

        LinearLayout ur = Ui.row(c);
        ur.setPadding(0, Ui.dp(c, 12), 0, 0);
        LinearLayout ut = new LinearLayout(c);
        ut.setOrientation(LinearLayout.VERTICAL);
        ut.addView(Ui.text(c, "Use my model", 16, Ui.TEXT, true));
        ut.addView(Ui.text(c, "When trained, it makes the pause decision", 12, Ui.MUTED, false));
        ur.addView(ut, Ui.weight(1));
        useCustom = new Switch(c);
        ur.addView(useCustom);
        m.addView(ur);
        useCustom.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton b, final boolean on) {
                if (settingSwitch) return;
                post("/api/settings", "{\"use_custom\":" + on + "}", on ? "Your model is in charge" : "Using Obico stock");
            }
        });

        LinearLayout tr = Ui.row(c);
        tr.setPadding(0, Ui.dp(c, 12), 0, 0);
        trainBtn = Ui.button(c, "Train now", Ui.ACCENT, Color.parseColor("#111111"), 0);
        trainBtn.setMinHeight(Ui.dp(c, 46));
        trainBtn.setTextSize(15);
        tr.addView(trainBtn, new LinearLayout.LayoutParams(-2, -2));
        trainState = Ui.text(c, "", 12, Ui.MUTED, false);
        trainState.setPadding(Ui.dp(c, 12), 0, 0, 0);
        tr.addView(trainState, Ui.weight(1));
        m.addView(tr);
        trainBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                post("/api/train", "{}", "Training started");
                ui.postDelayed(new Runnable() { public void run() { loadModel(); } }, 4000);
            }
        });
        root.addView(m);

        TextView tip = Ui.text(c, "Every print is recorded. Clean finishes are marked good automatically. "
                + "For a failure, open the print, slide to the first frame where it went wrong and tap "
                + "\"Failure started here\". You need 3 failed and 3 good prints; 10+ failures in different colors makes it strong.", 13, Ui.MUTED, false);
        LinearLayout tipCard = Ui.card(c);
        tipCard.addView(tip);
        root.addView(tipCard);

        LinearLayout tabRow = Ui.row(c);
        tabRow.setPadding(0, Ui.dp(c, 14), 0, Ui.dp(c, 4));
        String[] names = {"Review", "All", "Failures", "Good"};
        for (int i = 0; i < 4; i++) {
            final int idx = i;
            Button t = new Button(c);
            t.setText(names[i]);
            t.setAllCaps(false);
            t.setTextSize(13);
            t.setStateListAnimator(null);
            t.setMinHeight(Ui.dp(c, 36));
            t.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) { filter = FILTERS[idx]; paintTabs(); loadPrints(); }
            });
            tabs[i] = t;
            LinearLayout.LayoutParams lp = Ui.weight(1);
            if (i > 0) lp.leftMargin = Ui.dp(c, 6);
            tabRow.addView(t, lp);
        }
        paintTabs();
        root.addView(tabRow);

        list = new LinearLayout(c);
        list.setOrientation(LinearLayout.VERTICAL);
        root.addView(list);
        return sv;
    }

    private TextView[] cmpBox(LinearLayout parent, String label, boolean highlight) {
        Context c = this;
        LinearLayout b = new LinearLayout(c);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setBackground(Ui.box(c, Ui.SURFACE2, highlight ? Color.parseColor("#593ccf8e") : 0, 12));
        b.setPadding(Ui.dp(c, 10), Ui.dp(c, 10), Ui.dp(c, 10), Ui.dp(c, 10));
        b.addView(Ui.text(c, label, 11, Ui.MUTED, false));
        TextView big = Ui.text(c, "-", 22, Ui.TEXT, true);
        big.setTypeface(Ui.MONO, android.graphics.Typeface.BOLD);
        b.addView(big);
        TextView sub = Ui.text(c, "", 12, Ui.MUTED, false);
        b.addView(sub);
        LinearLayout.LayoutParams lp = Ui.weight(1);
        if (parent.getChildCount() > 0) lp.leftMargin = Ui.dp(c, 8);
        parent.addView(b, lp);
        return new TextView[]{big, sub};
    }

    private void paintTabs() {
        for (int i = 0; i < 4; i++) {
            boolean on = FILTERS[i].equals(filter);
            tabs[i].setBackground(Ui.box(this, on ? Ui.TEXT : Color.TRANSPARENT, on ? 0 : Ui.LINE, 99));
            tabs[i].setTextColor(on ? Color.parseColor("#111111") : Ui.MUTED);
        }
    }

    // ------------------------------------------------------------------ data
    private void loadModel() {
        net.execute(new Runnable() {
            public void run() {
                try {
                    final JSONObject s = new JSONObject(Api.get(TrainActivity.this, "/api/train", null, 8000).text());
                    final JSONObject st = new JSONObject(Api.get(TrainActivity.this, "/api/status", null, 8000).text());
                    ui.post(new Runnable() { public void run() { renderModel(s, st); } });
                } catch (final Exception e) {
                    ui.post(new Runnable() { public void run() { body.setText("Can't reach PrintWatch at " + Api.base(TrainActivity.this)); } });
                }
            }
        });
    }

    private void renderModel(JSONObject s, JSONObject st) {
        JSONObject r = s.optJSONObject("report"), c = s.optJSONObject("counts");
        boolean trained = s.optBoolean("trained");
        int minF = s.optInt("min_failed", 3), minG = s.optInt("min_good", 3);
        if (c != null) {
            progressTxt.setText("Failed prints " + c.optInt("failed") + "/" + minF + "   Good prints " + c.optInt("good") + "/" + minG
                    + (c.optInt("review") > 0 ? "\n" + c.optInt("review") + " to review" : ""));
        }
        boolean running = s.optBoolean("running");
        trainBtn.setEnabled(!running);
        trainBtn.setAlpha(running ? 0.4f : 1f);
        trainState.setText(running ? "Training..." : (!s.isNull("error") ? "Error: " + s.optString("error")
                : (r != null && r.has("trained_at") ? "Last run " + DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
                .format(new Date(r.optLong("trained_at") * 1000)) : "")));
        if (running) ui.postDelayed(new Runnable() { public void run() { loadModel(); } }, 2000);

        if (trained && r != null && r.optBoolean("ok")) {
            badge.setText("TRAINED");
            badge.setTextColor(Ui.OK);
            badge.setBackground(Ui.box(this, Color.parseColor("#263ccf8e"), 0, 99));
            body.setText("Measured on your own " + (r.optInt("failed_prints") + r.optInt("good_prints"))
                    + " prints with cross-validation: each print is tested by a model that never saw it.");
            cmp.setVisibility(View.VISIBLE);
            JSONObject cv = r.optJSONObject("cv"), ob = r.optJSONObject("obico");
            fill(mine, mineSub, cv);
            fill(obico, obicoSub, ob);
        } else {
            badge.setText(trained ? "TRAINED" : "COLLECTING");
            badge.setTextColor(Ui.ACCENT);
            badge.setBackground(Ui.box(this, Color.parseColor("#26f5a524"), 0, 99));
            body.setText("Obico's stock model protects your prints while you collect data. Label prints below.");
            cmp.setVisibility(View.GONE);
        }
        JSONObject set = st.optJSONObject("settings");
        if (set != null) {
            settingSwitch = true;
            useCustom.setChecked(set.optBoolean("use_custom", true));
            settingSwitch = false;
        }
    }

    private void fill(TextView big, TextView sub, JSONObject o) {
        if (o == null) { big.setText("-"); sub.setText(""); return; }
        big.setText(o.optInt("caught") + "/" + o.optInt("failed"));
        int fa = o.optInt("false_alarms");
        sub.setText("caught · " + fa + " false alarm" + (fa == 1 ? "" : "s")
                + (o.isNull("median_delay_s") ? "" : " · ~" + o.optInt("median_delay_s") + "s"));
    }

    private void loadPrints() {
        net.execute(new Runnable() {
            public void run() {
                try {
                    final JSONArray a = new JSONArray(Api.get(TrainActivity.this, "/api/prints", null, 10000).text());
                    ui.post(new Runnable() { public void run() { renderPrints(a); } });
                } catch (Exception e) {
                    ui.post(new Runnable() {
                        public void run() {
                            list.removeAllViews();
                            list.addView(Ui.text(TrainActivity.this, "Can't load prints.", 14, Ui.MUTED, false));
                        }
                    });
                }
            }
        });
    }

    private void renderPrints(JSONArray a) {
        list.removeAllViews();
        int shown = 0;
        for (int i = 0; i < a.length(); i++) {
            final JSONObject m = a.optJSONObject(i);
            if (m == null) continue;
            String label = m.isNull("label") ? null : m.optString("label");
            boolean rec = "recording".equals(m.optString("status"));
            boolean keep = filter.equals("all") || (filter.equals("review") ? (label == null && !rec) : filter.equals(label));
            if (!keep) continue;
            list.addView(printRow(m, label, rec));
            shown++;
        }
        if (shown == 0) {
            TextView t = Ui.text(this, filter.equals("review") ? "Nothing to review. Failed, stopped or flagged prints show up here."
                    : "No prints here yet.", 14, Ui.MUTED, false);
            t.setGravity(Gravity.CENTER);
            t.setPadding(0, Ui.dp(this, 30), 0, Ui.dp(this, 30));
            list.addView(t);
        }
    }

    private View printRow(final JSONObject m, String label, boolean rec) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int p = Ui.dp(c, 10);
        r.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);

        final ImageView th = new ImageView(c);
        th.setBackground(Ui.box(c, Color.BLACK, 0, 8));
        th.setClipToOutline(true);
        th.setScaleType(ImageView.ScaleType.CENTER_CROP);
        r.addView(th, new LinearLayout.LayoutParams(Ui.dp(c, 88), Ui.dp(c, 50)));
        if (!m.isNull("thumb")) {
            final String path = "/api/prints/" + m.optString("id") + "/frame/" + m.optInt("thumb");
            net.execute(new Runnable() {
                public void run() {
                    try {
                        Api.Resp rr = Api.get(TrainActivity.this, path, null, 10000);
                        if (rr.code == 200 && rr.body != null) {
                            final Bitmap bm = BitmapFactory.decodeByteArray(rr.body, 0, rr.body.length);
                            ui.post(new Runnable() { public void run() { th.setImageBitmap(bm); } });
                        }
                    } catch (Exception ignored) { }
                }
            });
        }

        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, Ui.dp(c, 8), 0);
        TextView jt = Ui.text(c, m.optString("job", "Print"), 15, Ui.TEXT, true);
        jt.setSingleLine(true);
        info.addView(jt);
        long started = (long) m.optDouble("started", 0);
        double ended = m.isNull("ended") ? System.currentTimeMillis() / 1000.0 : m.optDouble("ended");
        String sub = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(new Date(started * 1000))
                + " · " + Ui.mins((ended - started) / 60.0)
                + (m.isNull("end_state") ? "" : " · " + m.optString("end_state").toLowerCase())
                + (m.optBoolean("flagged") ? " · flagged" : "");
        TextView st = Ui.text(c, sub, 12, Ui.MUTED, false);
        st.setTypeface(Ui.MONO);
        info.addView(st);
        r.addView(info, Ui.weight(1));

        String bt; int bc;
        if (rec) { bt = "REC"; bc = Ui.INFO; }
        else if ("good".equals(label)) { bt = m.optBoolean("auto") ? "GOOD·AUTO" : "GOOD"; bc = Ui.OK; }
        else if ("failed".equals(label)) { bt = "FAILURE"; bc = Ui.DANGER; }
        else if ("ignore".equals(label)) { bt = "IGNORED"; bc = Ui.MUTED; }
        else { bt = "REVIEW"; bc = Ui.ACCENT; }
        TextView b = Ui.text(c, bt, 10, bc, true);
        b.setPadding(Ui.dp(c, 7), Ui.dp(c, 3), Ui.dp(c, 7), Ui.dp(c, 3));
        b.setBackground(Ui.box(c, Ui.SURFACE2, 0, 99));
        r.addView(b);

        r.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                Intent it = new Intent(TrainActivity.this, ReviewActivity.class);
                it.putExtra("id", m.optString("id"));
                startActivity(it);
            }
        });
        return r;
    }

    private void post(final String path, final String json, final String msg) {
        net.execute(new Runnable() {
            public void run() {
                boolean ok;
                try { ok = Api.post(TrainActivity.this, path, json).code == 200; } catch (Exception e) { ok = false; }
                final boolean fok = ok;
                ui.post(new Runnable() {
                    public void run() {
                        Toast.makeText(TrainActivity.this, fok ? msg : "Couldn't reach PrintWatch", Toast.LENGTH_SHORT).show();
                        loadModel();
                    }
                });
            }
        });
    }
}
