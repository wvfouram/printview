package dev.printwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Vibrator;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.OrientationEventListener;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
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

public class MainActivity extends Activity {
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newFixedThreadPool(3);
    private boolean running;
    private String etag;
    private JSONObject status;
    private boolean busy;
    private int failures;
    private Bitmap frame;
    private boolean theater;
    private OrientationEventListener orient;

    // Views (portrait and theater layouts each fill the ones they have; the rest stay null)
    private TextView dots, banner, pill, age, job, pct, remain, eta, layer, nozzle, bed, watchState, modelLine, serverLine;
    private LinearLayout events;
    private ImageView cam, lightBtn;
    private ProgressBar progress, score;
    private Button pauseBtn, stopBtn;
    private Switch autoPause;
    private Button[] sens = new Button[3];
    private static final String[] SENS = {"low", "medium", "high"};
    private boolean settingSwitch;
    private View overlayTop, overlayBottom;
    private final Runnable hideOverlay = new Runnable() { public void run() { showOverlay(false); } };

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Window w = getWindow();
        w.setStatusBarColor(Ui.BG);
        w.setNavigationBarColor(Ui.BG);
        w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        // After the rotate button locks an orientation, unlock it once the phone is physically turned to match,
        // so turning the phone keeps working like any video app.
        orient = new OrientationEventListener(this) {
            public void onOrientationChanged(int deg) {
                if (deg < 0) return;
                int req = getRequestedOrientation();
                boolean portraitNow = deg < 25 || deg > 335;
                boolean landNow = (deg > 65 && deg < 115) || (deg > 245 && deg < 295);
                if ((req == ActivityInfo.SCREEN_ORIENTATION_PORTRAIT && portraitNow)
                        || (req == ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE && landNow))
                    setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
            }
        };
        apply(getResources().getConfiguration());
    }

    @Override
    public void onConfigurationChanged(Configuration cfg) {
        super.onConfigurationChanged(cfg);
        apply(cfg);
    }

    private void apply(Configuration cfg) {
        theater = cfg.orientation == Configuration.ORIENTATION_LANDSCAPE;
        clearViews();
        View decor = getWindow().getDecorView();
        if (theater) {
            setContentView(buildTheater());
            decor.setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
            showOverlay(true);
        } else {
            setContentView(build());
            decor.setSystemUiVisibility(0);
        }
        if (frame != null) cam.setImageBitmap(frame);
        if (serverLine != null) serverLine.setText(Api.modeLabel(this));
        if (status != null) render(status);
    }

    private void clearViews() {
        ui.removeCallbacks(hideOverlay);
        dots = banner = pill = age = job = pct = remain = eta = layer = nozzle = bed = watchState = modelLine = serverLine = null;
        events = null;
        cam = lightBtn = null;
        progress = score = null;
        pauseBtn = stopBtn = null;
        autoPause = null;
        sens = new Button[3];
        overlayTop = overlayBottom = null;
    }

    private void goTheater(boolean on) {
        setRequestedOrientation(on ? ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE : ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
    }

    @Override
    public void onBackPressed() {
        if (theater) goTheater(false);
        else super.onBackPressed();
    }

    // ------------------------------------------------------------------ portrait layout
    private View build() {
        final Context c = this;
        ScrollView sv = new ScrollView(c);
        sv.setBackgroundColor(Ui.BG);
        sv.setFillViewport(true);
        sv.setVerticalScrollBarEnabled(false);
        LinearLayout root = new LinearLayout(c);
        root.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 16);
        root.setPadding(p, Ui.dp(c, 10), p, Ui.dp(c, 32));
        sv.addView(root);

        // header
        LinearLayout head = Ui.row(c);
        LinearLayout titleCol = new LinearLayout(c);
        titleCol.setOrientation(LinearLayout.VERTICAL);
        TextView title = Ui.text(c, "PrintWatch", 26, Ui.TEXT, true);
        title.setLetterSpacing(-0.01f);
        titleCol.addView(title);
        dots = Ui.text(c, "Connecting...", 12.5f, Ui.MUTED, false);
        dots.setPadding(0, Ui.dp(c, 4), 0, 0);
        titleCol.addView(dots);
        head.addView(titleCol, Ui.weight(1));
        ImageView gear = Ui.iconButton(c, "gear", Ui.MUTED, Ui.SURFACE);
        gear.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { serverDialog(); } });
        head.addView(gear, new LinearLayout.LayoutParams(Ui.dp(c, 44), Ui.dp(c, 44)));
        root.addView(head);

        banner = Ui.text(c, "", 13.5f, Color.parseColor("#ffd7d4"), false);
        banner.setBackground(Ui.box(c, Color.parseColor("#2b1514"), 0, 16));
        banner.setPadding(p, Ui.dp(c, 12), p, Ui.dp(c, 12));
        banner.setVisibility(View.GONE);
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-1, -2);
        bl.topMargin = Ui.dp(c, 12);
        root.addView(banner, bl);

        // camera
        FrameLayout camBox = new FrameLayout(c) {
            @Override
            protected void onMeasure(int wSpec, int hSpec) {
                int width = MeasureSpec.getSize(wSpec);
                super.onMeasure(wSpec, MeasureSpec.makeMeasureSpec(width * 9 / 16, MeasureSpec.EXACTLY));
            }
        };
        camBox.setBackground(Ui.box(c, Color.BLACK, 0, 22));
        camBox.setClipToOutline(true);
        LinearLayout.LayoutParams camLp = new LinearLayout.LayoutParams(-1, -2);
        camLp.topMargin = Ui.dp(c, 14);
        root.addView(camBox, camLp);
        cam = new ImageView(c);
        VideoFxActivity.apply(c, cam);
        cam.setScaleType(ImageView.ScaleType.FIT_CENTER);
        camBox.addView(cam, new FrameLayout.LayoutParams(-1, -1));
        cam.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { goTheater(true); } });
        View scrim = new View(c);
        scrim.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#80000000"), Color.TRANSPARENT, Color.TRANSPARENT, Color.parseColor("#99000000")}));
        camBox.addView(scrim, new FrameLayout.LayoutParams(-1, -1));
        addCamOverlays(camBox, false);

        // print status
        LinearLayout st = Ui.card(c);
        st.setPadding(Ui.dp(c, 18), Ui.dp(c, 18), Ui.dp(c, 18), Ui.dp(c, 18));
        job = Ui.text(c, "No active print", 15, Ui.MUTED, true);
        job.setSingleLine(true);
        job.setEllipsize(TextUtils.TruncateAt.END);
        st.addView(job);
        LinearLayout big = Ui.row(c);
        big.setGravity(Gravity.BOTTOM);
        pct = Ui.num(c, "--%", 54, Ui.TEXT, Ui.LIGHT);
        big.addView(pct, Ui.weight(1));
        LinearLayout etaCol = new LinearLayout(c);
        etaCol.setOrientation(LinearLayout.VERTICAL);
        etaCol.setGravity(Gravity.END);
        etaCol.setPadding(0, 0, 0, Ui.dp(c, 8));
        remain = Ui.num(c, "--", 20, Ui.TEXT, Ui.MEDIUM);
        remain.setGravity(Gravity.END);
        eta = Ui.text(c, "remaining", 12.5f, Ui.MUTED, false);
        eta.setGravity(Gravity.END);
        eta.setPadding(0, Ui.dp(c, 4), 0, 0);
        etaCol.addView(remain);
        etaCol.addView(eta);
        big.addView(etaCol);
        st.addView(big);
        st.addView(Ui.space(c, 12));
        progress = Ui.bar(c, Ui.ACCENT);
        st.addView(progress);
        st.addView(Ui.space(c, 16));
        LinearLayout stats = Ui.row(c);
        layer = stat(stats, "Layer");
        nozzle = stat(stats, "Nozzle");
        bed = stat(stats, "Bed");
        st.addView(stats);
        root.addView(st);

        // controls
        LinearLayout ctl = Ui.row(c);
        LinearLayout.LayoutParams ctlLp = new LinearLayout.LayoutParams(-1, -2);
        ctlLp.topMargin = Ui.dp(c, 12);
        pauseBtn = Ui.button(c, "Pause", Ui.ACCENT, Color.parseColor("#1a1206"), 0);
        stopBtn = Ui.button(c, "Stop", Ui.alpha(Ui.DANGER, 0.12f), Ui.DANGER, 0);
        Ui.icon(stopBtn, "stop", Ui.DANGER);
        LinearLayout.LayoutParams pw = Ui.weight(2);
        pw.rightMargin = Ui.dp(c, 10);
        ctl.addView(pauseBtn, pw);
        ctl.addView(stopBtn, Ui.weight(1));
        root.addView(ctl, ctlLp);
        wireMainButtons();

        // shortcuts
        String[][] nav = {{"Controls", "Speed, temps, AMS", "sliders", "controls"},
                {"Current job", "Preview, skip objects", "layers", "job"},
                {"Print from SD", "Start a sliced file", "sd", "files"},
                {"Timelapses", "Watch and save", "film", "timelapses"}};
        for (int i = 0; i < nav.length; i += 2) {
            LinearLayout nr = Ui.row(c);
            for (int k = i; k < i + 2; k++) {
                final String target = nav[k][3];
                View tile = tile(nav[k][0], nav[k][1], nav[k][2]);
                tile.setOnClickListener(new View.OnClickListener() {
                    public void onClick(View v) {
                        Class<?> cls = target.equals("controls") ? ControlsActivity.class : target.equals("job") ? JobActivity.class
                                : target.equals("files") ? FilesActivity.class : TimelapseActivity.class;
                        startActivity(new Intent(MainActivity.this, cls));
                    }
                });
                LinearLayout.LayoutParams nl = Ui.weight(1);
                if (k > i) nl.leftMargin = Ui.dp(c, 10);
                nr.addView(tile, nl);
            }
            LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(-1, -2);
            rl.topMargin = Ui.dp(c, i == 0 ? 12 : 10);
            root.addView(nr, rl);
        }

        View cmdTile = tile("Command center", "Web link: freeze, code, who's on", "shield");
        cmdTile.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { startActivity(new Intent(MainActivity.this, CommandActivity.class)); }
        });
        LinearLayout.LayoutParams ctl2 = new LinearLayout.LayoutParams(-1, -2);
        ctl2.topMargin = Ui.dp(c, 10);
        root.addView(cmdTile, ctl2);

        View strTile = tile("Data streams", "Live Arduino, printer and web traffic", "layers");
        strTile.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { startActivity(new Intent(MainActivity.this, StreamActivity.class)); }
        });
        LinearLayout.LayoutParams stl = new LinearLayout.LayoutParams(-1, -2);
        stl.topMargin = Ui.dp(c, 10);
        root.addView(strTile, stl);

        View vfxTile = tile("Video settings", "Colors, greyscale, invert, flip, zoom", "layers");
        vfxTile.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { startActivity(new Intent(MainActivity.this, VideoFxActivity.class)); }
        });
        LinearLayout.LayoutParams vfl = new LinearLayout.LayoutParams(-1, -2);
        vfl.topMargin = Ui.dp(c, 10);
        root.addView(vfxTile, vfl);

        // spaghetti watch
        LinearLayout sp = Ui.card(c);
        LinearLayout spHead = Ui.row(c);
        spHead.addView(Ui.heading(c, "Spaghetti watch"), Ui.weight(1));
        watchState = chip("-", Ui.MUTED);
        spHead.addView(watchState);
        sp.addView(spHead);
        sp.addView(Ui.space(c, 14));
        score = Ui.bar(c, Ui.OK);
        sp.addView(score);
        LinearLayout lbl = Ui.row(c);
        lbl.setPadding(0, Ui.dp(c, 6), 0, 0);
        TextView a = Ui.text(c, "Clean", 11.5f, Ui.FAINT, false);
        TextView z = Ui.text(c, "Pause", 11.5f, Ui.FAINT, false);
        z.setGravity(Gravity.END);
        lbl.addView(a, Ui.weight(1));
        lbl.addView(z, Ui.weight(1));
        sp.addView(lbl);
        sp.addView(divider());

        LinearLayout apRow = Ui.row(c);
        LinearLayout apText = new LinearLayout(c);
        apText.setOrientation(LinearLayout.VERTICAL);
        apText.addView(Ui.text(c, "Auto-pause", 16, Ui.TEXT, true));
        TextView apSub = Ui.text(c, "Pause the print when a failure is detected", 12.5f, Ui.MUTED, false);
        apSub.setPadding(0, Ui.dp(c, 3), 0, 0);
        apText.addView(apSub);
        apRow.addView(apText, Ui.weight(1));
        autoPause = new Switch(c);
        autoPause.setThumbTintList(new android.content.res.ColorStateList(
                new int[][]{{android.R.attr.state_checked}, {}}, new int[]{Ui.ACCENT, Ui.MUTED}));
        autoPause.setTrackTintList(new android.content.res.ColorStateList(
                new int[][]{{android.R.attr.state_checked}, {}}, new int[]{Ui.alpha(Ui.ACCENT, 0.45f), Ui.LINE}));
        apRow.addView(autoPause);
        sp.addView(apRow);
        autoPause.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            public void onCheckedChanged(CompoundButton bt, boolean on) {
                if (!settingSwitch) setting("{\"auto_pause\":" + on + "}", on ? "Auto-pause on" : "Auto-pause off");
            }
        });

        sp.addView(divider());
        sp.addView(Ui.text(c, "Sensitivity", 16, Ui.TEXT, true));
        sp.addView(Ui.space(c, 10));
        LinearLayout seg = Ui.row(c);
        seg.setBackground(Ui.box(c, Ui.SURFACE2, 0, 14));
        seg.setPadding(Ui.dp(c, 4), Ui.dp(c, 4), Ui.dp(c, 4), Ui.dp(c, 4));
        String[] names = {"Low", "Medium", "High"};
        for (int i = 0; i < 3; i++) {
            final int idx = i;
            Button sb = new Button(c);
            sb.setText(names[i]);
            sb.setAllCaps(false);
            sb.setStateListAnimator(null);
            sb.setTextSize(14);
            sb.setTypeface(Ui.MEDIUM);
            sb.setMinHeight(Ui.dp(c, 40));
            sb.setMinimumHeight(Ui.dp(c, 40));
            sb.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    paintSens(SENS[idx]);
                    setting("{\"sensitivity\":\"" + SENS[idx] + "\"}", null);
                }
            });
            sens[i] = sb;
            seg.addView(sb, Ui.weight(1));
        }
        sp.addView(seg);
        sp.addView(divider());

        LinearLayout trainRow = Ui.row(c);
        trainRow.setBackground(Ui.press(c, Ui.SURFACE2, 0, 14));
        trainRow.setPadding(Ui.dp(c, 14), Ui.dp(c, 12), Ui.dp(c, 10), Ui.dp(c, 12));
        trainRow.setClickable(true);
        ImageView spark = new ImageView(c);
        spark.setImageDrawable(Icons.of(c, "spark", Ui.ACCENT, 20));
        trainRow.addView(spark);
        LinearLayout trCol = new LinearLayout(c);
        trCol.setOrientation(LinearLayout.VERTICAL);
        trCol.setPadding(Ui.dp(c, 12), 0, 0, 0);
        trCol.addView(Ui.text(c, "Train detection", 15, Ui.TEXT, true));
        modelLine = Ui.text(c, "", 12.5f, Ui.MUTED, false);
        modelLine.setPadding(0, Ui.dp(c, 3), 0, 0);
        trCol.addView(modelLine);
        trainRow.addView(trCol, Ui.weight(1));
        ImageView chev = new ImageView(c);
        chev.setImageDrawable(Icons.of(c, "chev_r", Ui.FAINT, 18));
        trainRow.addView(chev);
        sp.addView(trainRow);
        trainRow.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { startActivity(new Intent(MainActivity.this, TrainActivity.class)); }
        });
        root.addView(sp);

        // activity
        LinearLayout ev = Ui.card(c);
        ev.addView(Ui.heading(c, "Activity"));
        events = new LinearLayout(c);
        events.setOrientation(LinearLayout.VERTICAL);
        events.setPadding(0, Ui.dp(c, 6), 0, 0);
        ev.addView(events);
        root.addView(ev);

        serverLine = Ui.text(c, "", 11.5f, Ui.FAINT, false);
        serverLine.setGravity(Gravity.CENTER);
        serverLine.setPadding(0, Ui.dp(c, 18), 0, 0);
        root.addView(serverLine);
        return sv;
    }

    /** State pill, LIVE badge, light and rotate buttons on the camera picture. */
    private void addCamOverlays(FrameLayout box, boolean big) {
        Context c = this;
        int m = Ui.dp(c, big ? 20 : 12);
        pill = Ui.text(c, "CONNECTING", 11.5f, Ui.TEXT, true);
        pill.setLetterSpacing(0.08f);
        pill.setBackground(Ui.box(c, Color.parseColor("#b3000000"), 0, 99));
        pill.setPadding(Ui.dp(c, 11), Ui.dp(c, 6), Ui.dp(c, 12), Ui.dp(c, 6));
        FrameLayout.LayoutParams pl = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.START);
        pl.setMargins(m, m, 0, 0);
        age = Ui.text(c, "", 11, Ui.TEXT, true);
        age.setLetterSpacing(0.08f);
        age.setBackground(Ui.box(c, Color.parseColor("#b3000000"), 0, 99));
        age.setPadding(Ui.dp(c, 10), Ui.dp(c, 6), Ui.dp(c, 10), Ui.dp(c, 6));
        if (!big) {
            box.addView(pill, pl);
            FrameLayout.LayoutParams al = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.END);
            al.setMargins(0, m, m, 0);
            box.addView(age, al);
        }
        LinearLayout btns = Ui.row(c);
        lightBtn = Ui.iconButton(c, "bulb", Ui.TEXT, Color.parseColor("#99000000"));
        lightBtn.setContentDescription("Chamber light");
        lightBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                boolean on = status != null && status.optJSONObject("printer") != null
                        && status.optJSONObject("printer").optBoolean("light", false);
                cmd(on ? "light_off" : "light_on", null);
                bump();
            }
        });
        int sz = Ui.dp(c, 42);
        if (!big) {
            btns.addView(lightBtn, new LinearLayout.LayoutParams(sz, sz));
            ImageView rot = Ui.iconButton(c, "expand", Ui.TEXT, Color.parseColor("#99000000"));
            rot.setContentDescription("Watch full screen");
            rot.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { goTheater(true); } });
            LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(sz, sz);
            rl.leftMargin = Ui.dp(c, 8);
            btns.addView(rot, rl);
            FrameLayout.LayoutParams bl = new FrameLayout.LayoutParams(-2, -2, Gravity.BOTTOM | Gravity.END);
            bl.setMargins(0, 0, m, m);
            box.addView(btns, bl);
        }
    }

    private View tile(String title, String sub, String icon) {
        Context c = this;
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setBackground(Ui.press(c, Ui.SURFACE, 0, 20));
        t.setPadding(Ui.dp(c, 16), Ui.dp(c, 16), Ui.dp(c, 12), Ui.dp(c, 16));
        t.setClickable(true);
        ImageView ic = new ImageView(c);
        ic.setImageDrawable(Icons.of(c, icon, Ui.ACCENT, 20));
        ic.setBackground(Ui.box(c, Ui.alpha(Ui.ACCENT, 0.12f), 0, 12));
        int s = Ui.dp(c, 38);
        ic.setScaleType(ImageView.ScaleType.CENTER);
        t.addView(ic, new LinearLayout.LayoutParams(s, s));
        TextView tt = Ui.text(c, title, 15, Ui.TEXT, true);
        tt.setPadding(0, Ui.dp(c, 12), 0, 0);
        tt.setSingleLine(true);
        t.addView(tt);
        TextView ts = Ui.text(c, sub, 12, Ui.MUTED, false);
        ts.setPadding(0, Ui.dp(c, 3), 0, 0);
        ts.setSingleLine(true);
        ts.setEllipsize(TextUtils.TruncateAt.END);
        t.addView(ts);
        return t;
    }

    private TextView chip(String s, int color) {
        TextView t = Ui.text(this, s, 12, color, true);
        t.setBackground(Ui.box(this, Ui.SURFACE2, 0, 99));
        t.setPadding(Ui.dp(this, 10), Ui.dp(this, 5), Ui.dp(this, 10), Ui.dp(this, 5));
        return t;
    }

    private View divider() {
        View v = new View(this);
        v.setBackgroundColor(Ui.LINE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, 1);
        lp.topMargin = Ui.dp(this, 16);
        lp.bottomMargin = Ui.dp(this, 16);
        v.setLayoutParams(lp);
        return v;
    }

    private TextView stat(LinearLayout parent, String label) {
        Context c = this;
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackground(Ui.box(c, Ui.SURFACE2, 0, 14));
        box.setPadding(Ui.dp(c, 12), Ui.dp(c, 10), Ui.dp(c, 10), Ui.dp(c, 10));
        TextView l = Ui.text(c, label, 12, Ui.MUTED, false);
        box.addView(l);
        TextView v = Ui.num(c, "--", 17, Ui.TEXT, Ui.MEDIUM);
        v.setPadding(0, Ui.dp(c, 4), 0, 0);
        v.setSingleLine(true);
        box.addView(v);
        LinearLayout.LayoutParams lp = Ui.weight(1);
        if (parent.getChildCount() > 0) lp.leftMargin = Ui.dp(c, 8);
        parent.addView(box, lp);
        return v;
    }

    private void wireMainButtons() {
        pauseBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { cmd((String) pauseBtn.getTag(), null); bump(); }
        });
        stopBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { confirmStop(); bump(); }
        });
    }

    // ------------------------------------------------------------------ landscape "theater" layout
    private View buildTheater() {
        final Context c = this;
        FrameLayout f = new FrameLayout(c);
        f.setBackgroundColor(Color.BLACK);
        cam = new ImageView(c);
        VideoFxActivity.apply(c, cam);
        cam.setScaleType(ImageView.ScaleType.FIT_CENTER);
        f.addView(cam, new FrameLayout.LayoutParams(-1, -1));
        cam.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { showOverlay(overlayTop.getVisibility() != View.VISIBLE || overlayTop.getAlpha() < 0.5f); }
        });
        int m = Ui.dp(c, 20);

        // top bar: back, state, job name, live badge, light
        LinearLayout top = Ui.row(c);
        top.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{Color.parseColor("#b3000000"), Color.TRANSPARENT}));
        top.setPadding(m, Ui.dp(c, 16), m, Ui.dp(c, 36));
        ImageView back = Ui.iconButton(c, "chev_l", Ui.TEXT, Color.parseColor("#66000000"));
        back.setContentDescription("Back");
        back.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { goTheater(false); } });
        int sz = Ui.dp(c, 42);
        top.addView(back, new LinearLayout.LayoutParams(sz, sz));
        addCamOverlays(new FrameLayout(c), true);
        LinearLayout.LayoutParams pl = new LinearLayout.LayoutParams(-2, -2);
        pl.leftMargin = Ui.dp(c, 12);
        top.addView(pill, pl);
        job = Ui.text(c, "", 15, Ui.TEXT, true);
        job.setSingleLine(true);
        job.setEllipsize(TextUtils.TruncateAt.END);
        job.setPadding(Ui.dp(c, 12), 0, Ui.dp(c, 12), 0);
        top.addView(job, Ui.weight(1));
        top.addView(age);
        LinearLayout.LayoutParams ll = new LinearLayout.LayoutParams(sz, sz);
        ll.leftMargin = Ui.dp(c, 10);
        top.addView(lightBtn, ll);
        f.addView(top, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));
        overlayTop = top;

        // bottom bar: big percent, time left, stats, progress, pause/stop
        LinearLayout bot = new LinearLayout(c);
        bot.setOrientation(LinearLayout.VERTICAL);
        bot.setBackground(new GradientDrawable(GradientDrawable.Orientation.BOTTOM_TOP,
                new int[]{Color.parseColor("#cc000000"), Color.parseColor("#66000000"), Color.TRANSPARENT}));
        bot.setPadding(m, Ui.dp(c, 40), m, Ui.dp(c, 18));
        LinearLayout r = Ui.row(c);
        r.setGravity(Gravity.BOTTOM);
        pct = Ui.num(c, "--%", 44, Ui.TEXT, Ui.LIGHT);
        r.addView(pct);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 18), 0, 0, Ui.dp(c, 6));
        LinearLayout tl = Ui.row(c);
        remain = Ui.num(c, "--", 17, Ui.TEXT, Ui.MEDIUM);
        tl.addView(remain);
        eta = Ui.text(c, "", 13, Ui.MUTED, false);
        eta.setPadding(Ui.dp(c, 10), 0, 0, 0);
        tl.addView(eta);
        info.addView(tl);
        LinearLayout sl = Ui.row(c);
        sl.setPadding(0, Ui.dp(c, 6), 0, 0);
        layer = miniStat(sl, "Layer");
        nozzle = miniStat(sl, "Nozzle");
        bed = miniStat(sl, "Bed");
        watchState = Ui.text(c, "", 13, Ui.MUTED, false);
        sl.addView(watchState);
        info.addView(sl);
        r.addView(info, Ui.weight(1));
        pauseBtn = Ui.button(c, "Pause", Ui.ACCENT, Color.parseColor("#1a1206"), 0);
        pauseBtn.setPadding(Ui.dp(c, 22), 0, Ui.dp(c, 22), 0);
        stopBtn = Ui.button(c, "Stop", Ui.alpha(Ui.DANGER, 0.22f), Ui.DANGER, 0);
        stopBtn.setPadding(Ui.dp(c, 20), 0, Ui.dp(c, 20), 0);
        Ui.icon(stopBtn, "stop", Ui.DANGER);
        LinearLayout.LayoutParams pbl = new LinearLayout.LayoutParams(-2, Ui.dp(c, 50));
        pbl.bottomMargin = Ui.dp(c, 4);
        r.addView(pauseBtn, pbl);
        LinearLayout.LayoutParams sbl = new LinearLayout.LayoutParams(-2, Ui.dp(c, 50));
        sbl.leftMargin = Ui.dp(c, 10);
        sbl.bottomMargin = Ui.dp(c, 4);
        r.addView(stopBtn, sbl);
        bot.addView(r);
        bot.addView(Ui.space(c, 14));
        progress = Ui.bar(c, Ui.ACCENT);
        progress.setLayoutParams(new LinearLayout.LayoutParams(-1, Ui.dp(c, 5)));
        bot.addView(progress);
        f.addView(bot, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        overlayBottom = bot;
        wireMainButtons();
        return f;
    }

    private TextView miniStat(LinearLayout parent, String label) {
        Context c = this;
        TextView l = Ui.text(c, label + " ", 13, Ui.MUTED, false);
        parent.addView(l);
        TextView v = Ui.num(c, "--", 13, Ui.TEXT, Ui.MEDIUM);
        v.setPadding(0, 0, Ui.dp(c, 16), 0);
        parent.addView(v);
        return v;
    }

    /** Theater controls fade away after a few seconds; tap the picture to bring them back. */
    private void showOverlay(boolean show) {
        if (overlayTop == null) return;
        ui.removeCallbacks(hideOverlay);
        for (final View v : new View[]{overlayTop, overlayBottom}) {
            v.animate().cancel();
            if (show) {
                v.setVisibility(View.VISIBLE);
                v.animate().alpha(1f).setDuration(200).start();
            } else {
                v.animate().alpha(0f).setDuration(250).withEndAction(new Runnable() {
                    public void run() { v.setVisibility(View.INVISIBLE); }
                }).start();
            }
        }
        if (show) ui.postDelayed(hideOverlay, 5000);
    }

    private void bump() {
        if (theater) showOverlay(true);
    }

    // ------------------------------------------------------------------ lifecycle / polling
    @Override
    protected void onResume() {
        super.onResume();
        running = true;
        if (orient.canDetectOrientation()) orient.enable();
        VideoFxActivity.apply(this, cam);
        if (serverLine != null) serverLine.setText(Api.modeLabel(this));
        pollStatus();
        pollCamera();
    }

    @Override
    protected void onPause() {
        super.onPause();
        running = false;
        orient.disable();
    }

    private void pollStatus() {
        if (!running) return;
        net.execute(new Runnable() {
            public void run() {
                JSONObject s = null;
                String err = null;
                try {
                    Api.Resp r = Api.get(MainActivity.this, "/api/status", null, 6000);
                    if (r.code == 200) s = new JSONObject(r.text());
                    else err = "PrintWatch answered HTTP " + r.code;
                } catch (Exception e) {
                    err = e.getClass().getSimpleName();
                }
                final JSONObject fs = s;
                final String fe = err;
                ui.post(new Runnable() {
                    public void run() {
                        if (fs != null) {
                            failures = 0;
                            render(fs);
                            if (serverLine != null) serverLine.setText(Api.modeLabel(MainActivity.this));
                        } else offline(fe);
                        ui.postDelayed(new Runnable() { public void run() { pollStatus(); } }, fs != null ? 1000 : 3000);
                    }
                });
            }
        });
    }

    private void pollCamera() {
        if (!running) return;
        net.execute(new Runnable() {
            public void run() {
                Bitmap bmp = null;
                boolean ok = false;
                try {
                    Api.Resp r = Api.get(MainActivity.this, "/snapshot.jpg", etag, 8000);
                    if (r.code == 200 && r.body != null) {
                        bmp = BitmapFactory.decodeByteArray(r.body, 0, r.body.length);
                        etag = r.etag;
                        ok = true;
                    } else if (r.code == 304) ok = true;
                } catch (Exception ignored) { }
                final Bitmap fb = bmp;
                final boolean fok = ok;
                ui.post(new Runnable() {
                    public void run() {
                        if (fb != null) {
                            frame = fb;
                            if (cam != null) cam.setImageBitmap(fb);
                        }
                        ui.postDelayed(new Runnable() { public void run() { pollCamera(); } }, fok ? 1000 : 3000);
                    }
                });
            }
        });
    }

    // ------------------------------------------------------------------ render
    private static final String[][] STATES = {
            {"RUNNING", "PRINTING", "#34d399"}, {"PAUSE", "PAUSED", "#ffb224"}, {"PREPARE", "PREPARING", "#60a5fa"},
            {"SLICING", "PREPARING", "#60a5fa"}, {"FINISH", "FINISHED", "#34d399"}, {"FAILED", "STOPPED", "#ff5d55"},
            {"IDLE", "IDLE", "#8d929b"}};

    private void offline(String err) {
        failures++;
        if (failures < 2) return;
        if (dots != null) {
            dots.setText("●  Offline");
            dots.setTextColor(Ui.DANGER);
        }
        if (banner != null) {
            banner.setVisibility(View.VISIBLE);
            banner.setText(Api.paired(this)
                    ? "Can't reach your Pi, at home or remotely. Check it's powered on and online. (" + err + ")"
                    : "Can't reach PrintWatch at " + Api.lan(this) + ".\nOpen the app once on your home Wi-Fi so it can pair for remote access. (" + err + ")");
        }
        pill.setText("●  OFFLINE");
        pill.setTextColor(Ui.DANGER);
        dim(pauseBtn, false);
        dim(stopBtn, false);
    }

    private static void dim(View v, boolean on) {
        v.setEnabled(on);
        v.setAlpha(on ? 1f : 0.35f);
    }

    private void render(JSONObject s) {
        status = s;
        JSONObject p = s.optJSONObject("printer"), cm = s.optJSONObject("camera"), d = s.optJSONObject("detector");
        JSONObject set = s.optJSONObject("settings"), tr = s.optJSONObject("training");
        if (p == null || cm == null || d == null) return;
        boolean pc = p.optBoolean("connected"), cc = cm.optBoolean("connected");
        if (dots != null) {
            String where = Api.modeLabel(this).startsWith("Away") ? "Away" : "Home";
            dots.setText(pc && cc ? "●  Connected · " + where
                    : "●  " + (pc ? "Camera offline" : cc ? "Printer offline" : "Printer and camera offline"));
            dots.setTextColor(pc && cc ? Ui.OK : Ui.DANGER);
        }

        if (banner != null) {
            String note = null;
            if (!pc) note = "Printer not connected" + (p.isNull("error") ? "" : ": " + p.optString("error"));
            if (!d.isNull("error")) note = (note == null ? "" : note + "\n") + "Spaghetti detection off: " + d.optString("error");
            JSONObject bc = s.optJSONObject("bedctl");
            if (bc != null && bc.optBoolean("enabled")) {
                String bn = null;
                if (!bc.isNull("fault")) bn = "Bed servo FAULT (heating held off): " + bc.optString("fault");
                else if (!bc.isNull("alert") && bc.optDouble("bed_target", 0) > 0) bn = "Bed heating off: " + bc.optString("alert");
                if (bn != null) note = (note == null ? "" : note + "\n") + bn;
            }
            JSONObject hm = s.optJSONObject("hms");
            org.json.JSONArray hi = hm == null ? null : hm.optJSONArray("items");
            if (hi != null && hi.length() > 0) {
                StringBuilder sb = new StringBuilder("Printer errors (" + hi.length() + "):");
                for (int i = 0; i < hi.length(); i++) {
                    JSONObject e = hi.optJSONObject(i);
                    if (e == null) continue;
                    sb.append("\n\n").append(e.optString("level")).append(" \u00b7 ")
                      .append(e.isNull("url") ? "" : "HMS_").append(e.optString("code"))
                      .append("\n").append(e.optString("text"));
                }
                note = (note == null ? "" : note + "\n\n") + sb;
            }
            banner.setVisibility(note == null ? View.GONE : View.VISIBLE);
            if (note != null) banner.setText(note);
        }

        String state = p.optString("state", "UNKNOWN");
        String label = pc ? state : "OFFLINE";
        int col = Ui.FAINT;
        for (String[] st : STATES) if (st[0].equals(state) && pc) { label = st[1]; col = Color.parseColor(st[2]); }
        pill.setText("●  " + label);
        pill.setTextColor(pc ? col : Ui.DANGER);

        boolean active = state.equals("RUNNING") || state.equals("PAUSE") || state.equals("PREPARE");
        String j = p.optString("job", "");
        job.setText(j.isEmpty() ? (active ? "Print" : theater ? "" : "No active print") : j);
        if (!theater) job.setTextColor(j.isEmpty() && !active ? Ui.MUTED : Ui.TEXT);
        boolean hasPct = !p.isNull("percent") && !state.equals("IDLE");
        int percent = p.optInt("percent", 0);
        pct.setText(hasPct ? percent + "%" : "--%");
        progress.setProgress(hasPct ? percent * 10 : 0);
        progress.setProgressTintList(android.content.res.ColorStateList.valueOf(
                state.equals("FAILED") ? Ui.DANGER : state.equals("FINISH") ? Ui.OK : Ui.ACCENT));
        double rem = p.isNull("remaining_min") ? -1 : p.optDouble("remaining_min", -1);
        remain.setText(active ? Ui.mins(rem) + (theater ? " left" : "") : "--");
        if (active && rem > 0) {
            Date done = new Date(System.currentTimeMillis() + (long) (rem * 60000));
            eta.setText((theater ? "done " : "Done at ") + DateFormat.getTimeInstance(DateFormat.SHORT).format(done));
        } else eta.setText(theater ? "" : "remaining");
        layer.setText(!p.isNull("layer") && p.optInt("total_layers", 0) > 0 ? p.optInt("layer") + " / " + p.optInt("total_layers") : "--");
        nozzle.setText(temp(p, "nozzle", "nozzle_target"));
        JSONObject bcs = s.optJSONObject("bedctl");
        boolean heating = bcs != null && bcs.optBoolean("enabled") && "close".equals(bcs.optString("state"));
        boolean bcOn = bcs != null && bcs.optBoolean("enabled");
        bed.setText(temp(p, "bed", "bed_target") + (bcOn ? (heating ? " \uD83D\uDD25" : " \uD83E\uDDCA") : ""));

        if (state.equals("PAUSE")) styleMain("Resume", Ui.OK, "resume", pc);
        else styleMain("Pause", Ui.ACCENT, "pause", pc && state.equals("RUNNING"));
        dim(stopBtn, pc && active);
        boolean light = p.optBoolean("light", false);
        lightBtn.setImageDrawable(Icons.of(this, light ? "bulb_on" : "bulb", light ? Ui.ACCENT : Ui.TEXT, 22));

        double age_s = cm.isNull("frame_age_s") ? -1 : cm.optDouble("frame_age_s", -1);
        boolean live = cc && age_s >= 0 && age_s < 4;
        age.setText(cc && age_s >= 0 ? (live ? "● LIVE" : Math.round(age_s) + "s ago") : "");
        age.setTextColor(live ? Color.parseColor("#ff6b63") : Ui.TEXT);
        age.setVisibility(age.getText().length() > 0 ? View.VISIBLE : View.GONE);

        // detector
        boolean custom = "custom".equals(d.optString("mode"));
        double sc = custom ? d.optDouble("custom_score", 0) : d.optDouble("score", 0);
        double pa = custom ? d.optDouble("custom_pause_at", 0.8) : d.optDouble("pause_at", 0.78);
        double wa = custom ? d.optDouble("custom_warn_at", 0.6) : d.optDouble("warn_at", 0.38);
        if (Double.isNaN(sc)) sc = 0;
        double max = custom ? 1.0 : pa * 1.3;
        int risk = sc >= pa ? Ui.DANGER : sc >= wa ? Ui.ACCENT : Ui.OK;
        if (score != null) {
            score.setProgress((int) Math.min(1000, sc / max * 1000));
            score.setProgressTintList(android.content.res.ColorStateList.valueOf(risk));
        }
        String ws;
        int wc = Ui.MUTED;
        int warm = d.optInt("warmup_s", 0);
        if (!d.optBoolean("enabled")) ws = "Off";
        else if (!state.equals("RUNNING")) ws = state.equals("PAUSE") ? "Paused" : "Idle";
        else if (d.optBoolean("acted")) { ws = "Failure flagged"; wc = Ui.DANGER; }
        else if (warm > 0) ws = "Warming up " + warm / 60 + ":" + String.format("%02d", warm % 60);
        else { ws = "Watching" + (d.isNull("infer_ms") || theater ? "" : " · " + d.optInt("infer_ms") + " ms"); wc = risk; }
        watchState.setText(theater ? (state.equals("RUNNING") ? "● Spaghetti watch: " + ws.toLowerCase() : "") : ws);
        watchState.setTextColor(wc);

        if (set != null && autoPause != null) {
            settingSwitch = true;
            autoPause.setChecked(set.optBoolean("auto_pause"));
            settingSwitch = false;
            paintSens(set.optString("sensitivity", "medium"));
        }
        if (tr != null && modelLine != null) {
            int review = tr.optInt("review", 0);
            String sum = tr.isNull("summary") ? null : tr.optString("summary");
            modelLine.setText((custom ? "Your model is in charge" + (sum != null ? " · " + sum : "")
                    : tr.optBoolean("trained") ? "Obico stock (your model is off)" : "Obico stock · label prints to train yours")
                    + (review > 0 ? "\n" + review + " print" + (review == 1 ? "" : "s") + " to review" : ""));
        }

        if (events != null) renderEvents(s.optJSONArray("events"));
    }

    private void renderEvents(JSONArray ev) {
        Context c = this;
        events.removeAllViews();
        if (ev == null || ev.length() == 0) {
            TextView t = Ui.text(c, "Nothing yet.", 14, Ui.MUTED, false);
            t.setPadding(0, Ui.dp(c, 8), 0, 0);
            events.addView(t);
            return;
        }
        DateFormat tf = DateFormat.getTimeInstance(DateFormat.SHORT);
        for (int i = 0; i < Math.min(8, ev.length()); i++) {
            JSONObject e = ev.optJSONObject(i);
            if (e == null) continue;
            LinearLayout r = Ui.row(c);
            r.setGravity(Gravity.TOP);
            r.setPadding(0, Ui.dp(c, 10), 0, 0);
            String text = e.optString("text");
            String lo = text.toLowerCase();
            int dot = lo.contains("fail") || lo.contains("stop") || lo.contains("spaghetti") ? Ui.DANGER
                    : lo.contains("pause") || lo.contains("warn") ? Ui.ACCENT
                    : lo.contains("finish") || lo.contains("done") ? Ui.OK : Ui.FAINT;
            View d = new View(c);
            d.setBackground(Ui.box(c, dot, 0, 99));
            LinearLayout.LayoutParams dl = new LinearLayout.LayoutParams(Ui.dp(c, 7), Ui.dp(c, 7));
            dl.topMargin = Ui.dp(c, 6);
            dl.rightMargin = Ui.dp(c, 12);
            r.addView(d, dl);
            TextView tt = Ui.text(c, text, 14, Ui.TEXT, false);
            r.addView(tt, Ui.weight(1));
            TextView tm = Ui.num(c, tf.format(new Date(e.optLong("t") * 1000)), 12.5f, Ui.FAINT, Ui.REGULAR);
            tm.setPadding(Ui.dp(c, 10), Ui.dp(c, 1), 0, 0);
            r.addView(tm);
            events.addView(r);
        }
    }

    private String temp(JSONObject p, String k, String t) {
        if (p.isNull(k)) return "--";
        String v = Math.round(p.optDouble(k)) + "°";
        if (!p.isNull(t) && p.optDouble(t) > 0) v += " / " + Math.round(p.optDouble(t)) + "°";
        return v;
    }

    private void styleMain(String text, int color, String action, boolean enabled) {
        pauseBtn.setText(text);
        pauseBtn.setTag(action);
        pauseBtn.setBackground(Ui.press(this, color, 0, 16));
        int fg = Color.parseColor("#1a1206");
        pauseBtn.setTextColor(fg);
        Ui.icon(pauseBtn, action.equals("resume") ? "play" : "pause", fg);
        dim(pauseBtn, enabled);
    }

    private void paintSens(String v) {
        for (int i = 0; i < 3; i++) {
            if (sens[i] == null) return;
            boolean on = SENS[i].equals(v);
            sens[i].setBackground(Ui.box(this, on ? Ui.LINE : Color.TRANSPARENT, 0, 11));
            sens[i].setTextColor(on ? Ui.TEXT : Ui.MUTED);
        }
    }

    // ------------------------------------------------------------------ actions
    private void cmd(final String action, final String extra) {
        if (busy || action == null) return;
        busy = true;
        buzz(30);
        net.execute(new Runnable() {
            public void run() {
                String msg;
                try {
                    String body = "{\"action\":\"" + action + "\"" + (extra == null ? "" : "," + extra) + "}";
                    Api.Resp r = Api.post(MainActivity.this, "/api/cmd", body);
                    JSONObject j = new JSONObject(r.text());
                    msg = j.optBoolean("ok") ? label(action) : "Failed: " + j.optString("error", "HTTP " + r.code);
                } catch (Exception e) {
                    msg = "Can't reach PrintWatch";
                }
                final String m = msg;
                ui.post(new Runnable() {
                    public void run() {
                        toast(m);
                        ui.postDelayed(new Runnable() { public void run() { busy = false; } }, 700);
                    }
                });
            }
        });
    }

    private static String label(String a) {
        if (a.equals("pause")) return "Pausing...";
        if (a.equals("resume")) return "Resuming...";
        if (a.equals("stop")) return "Stopping...";
        if (a.equals("light_on")) return "Light on";
        if (a.equals("light_off")) return "Light off";
        return "Sent";
    }

    private void setting(final String json, final String msg) {
        net.execute(new Runnable() {
            public void run() {
                boolean ok;
                try { ok = Api.post(MainActivity.this, "/api/settings", json).code == 200; } catch (Exception e) { ok = false; }
                final boolean fok = ok;
                ui.post(new Runnable() {
                    public void run() {
                        if (!fok) toast("Couldn't save setting");
                        else if (msg != null) toast(msg);
                    }
                });
            }
        });
    }

    private void confirmStop() {
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("Stop this print?")
                .setMessage("This cancels the job on the printer. It can't be resumed.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Stop print", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface di, int w) {
                        buzz(60);
                        cmd("stop", "\"confirm\":\"STOP\"");
                    }
                })
                .show();
    }

    private void serverDialog() {
        final EditText in = new EditText(this);
        in.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        in.setText(Api.base(this));
        in.setSelectAllOnFocus(true);
        in.setTextColor(Ui.TEXT);
        FrameLayout f = new FrameLayout(this);
        int p = Ui.dp(this, 20);
        f.setPadding(p, Ui.dp(this, 8), p, 0);
        f.addView(in);
        new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle("PrintWatch address")
                .setMessage("The Pi's address on your home Wi-Fi.\n\n" + remoteStatus())
                .setView(f)
                .setNegativeButton("Cancel", null)
                .setNeutralButton("Re-pair", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        Api.forgetPairing(MainActivity.this);
                        toast("This phone will pair again next time it's on your home Wi-Fi");
                    }
                })
                .setPositiveButton("Save", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) {
                        Api.setBase(MainActivity.this, in.getText().toString());
                        if (serverLine != null) serverLine.setText(Api.modeLabel(MainActivity.this));
                        etag = null;
                    }
                })
                .show();
    }

    private String remoteStatus() {
        if (!Api.paired(this)) return "Remote access: not paired yet. It pairs automatically when the app runs on your home Wi-Fi.";
        StringBuilder sb = new StringBuilder("Remote access: paired \u2713\nAway address: ");
        String rb = Api.remoteBase(this);
        sb.append(rb == null ? "unknown" : rb.replace("https://", ""));
        try {
            org.json.JSONObject info = new org.json.JSONObject(Api.prefs(this).getString("rinfo", "{}"));
            org.json.JSONObject up = info.optJSONObject("upnp");
            if (rb == null) sb.append("\nThe Pi doesn't know your home's public address: turn on UPnP in your router, or forward TCP ")
                    .append(info.optInt("port", 8443)).append(" to the Pi and set REMOTE_HOST in its .env.");
            else if (up != null && !up.optBoolean("mapped")) sb.append("\nRouter forwarding: not automatic (")
                    .append(up.optString("error")).append("). Forward TCP ").append(info.optInt("port", 8443)).append(" to the Pi by hand.");
            else if (up != null) sb.append("\nRouter forwarding: automatic (UPnP) \u2713");
            if (info.optBoolean("cgnat")) sb.append("\nWarning: your internet provider shares your public address (CGNAT); remote access may not work.");
        } catch (Exception ignored) { }
        return sb.toString();
    }

    private void toast(String m) {
        Toast.makeText(this, m, Toast.LENGTH_SHORT).show();
    }

    @SuppressWarnings("deprecation")
    private void buzz(int ms) {
        try {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v != null) v.vibrate(ms);
        } catch (Exception ignored) { }
    }
}
