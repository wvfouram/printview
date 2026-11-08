package dev.printwatch;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.ColorMatrix;
import android.graphics.ColorMatrixColorFilter;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

/** Video settings: how the camera looks on this phone only (colors, greyscale, invert, flip, zoom). */
public class VideoFxActivity extends Base {
    static final String[] SL = {"bright", "contrast", "sat", "hue", "zoom"};
    static final String[] SL_NAME = {"Brightness", "Contrast", "Saturation", "Hue shift", "Zoom"};
    static final int[][] SL_RANGE = {{20, 250, 100}, {20, 250, 100}, {0, 300, 100}, {0, 360, 0}, {100, 400, 100}};
    static final String[] CK = {"gray", "invert", "sepia", "night", "flipH", "flipV"};
    static final String[] CK_NAME = {"Greyscale", "Invert colors", "Sepia", "Night vision", "Flip sideways", "Flip upside down"};

    private final SeekBar[] bars = new SeekBar[SL.length];
    private final TextView[] vals = new TextView[SL.length];
    private final CheckBox[] boxes = new CheckBox[CK.length];

    static SharedPreferences p(Context c) { return c.getSharedPreferences("videofx", Context.MODE_PRIVATE); }

    /** Apply the saved look to a camera view. Call after layout or whenever it may have changed. */
    static void apply(Context c, ImageView v) {
        if (v == null) return;
        SharedPreferences s = p(c);
        ColorMatrix m = new ColorMatrix();
        float b = s.getInt("bright", 100) / 100f, ct = s.getInt("contrast", 100) / 100f;
        ColorMatrix t = new ColorMatrix(new float[]{
                ct * b, 0, 0, 0, 128 * (1 - ct),
                0, ct * b, 0, 0, 128 * (1 - ct),
                0, 0, ct * b, 0, 128 * (1 - ct),
                0, 0, 0, 1, 0});
        m.postConcat(t);
        ColorMatrix sat = new ColorMatrix();
        sat.setSaturation(s.getInt("sat", 100) / 100f);
        m.postConcat(sat);
        int hue = s.getInt("hue", 0);
        if (hue != 0) m.postConcat(hueMatrix(hue));
        if (s.getBoolean("gray", false) || s.getBoolean("night", false)) {
            ColorMatrix g = new ColorMatrix(); g.setSaturation(0); m.postConcat(g);
        }
        if (s.getBoolean("sepia", false)) m.postConcat(new ColorMatrix(new float[]{
                .393f, .769f, .189f, 0, 0, .349f, .686f, .168f, 0, 0, .272f, .534f, .131f, 0, 0, 0, 0, 0, 1, 0}));
        if (s.getBoolean("night", false)) m.postConcat(new ColorMatrix(new float[]{
                .25f, 0, 0, 0, 0, 0, 1.3f, 0, 0, 10, 0, 0, .25f, 0, 0, 0, 0, 0, 1, 0}));
        if (s.getBoolean("invert", false)) m.postConcat(new ColorMatrix(new float[]{
                -1, 0, 0, 0, 255, 0, -1, 0, 0, 255, 0, 0, -1, 0, 255, 0, 0, 0, 1, 0}));
        v.setColorFilter(new ColorMatrixColorFilter(m));
        float z = s.getInt("zoom", 100) / 100f;
        v.setScaleX((s.getBoolean("flipH", false) ? -1 : 1) * z);
        v.setScaleY((s.getBoolean("flipV", false) ? -1 : 1) * z);
        if (v.getParent() instanceof android.view.ViewGroup) {
            android.view.ViewGroup g = (android.view.ViewGroup) v.getParent();
            g.setClipChildren(true);
            g.setClipToPadding(true);
        }
    }

    private static ColorMatrix hueMatrix(float deg) {
        double a = Math.toRadians(deg);
        float c = (float) Math.cos(a), s = (float) Math.sin(a);
        float lr = .213f, lg = .715f, lb = .072f;
        return new ColorMatrix(new float[]{
                lr + c * (1 - lr) + s * (-lr), lg + c * (-lg) + s * (-lg), lb + c * (-lb) + s * (1 - lb), 0, 0,
                lr + c * (-lr) + s * .143f, lg + c * (1 - lg) + s * .140f, lb + c * (-lb) + s * -.283f, 0, 0,
                lr + c * (-lr) + s * (-(1 - lr)), lg + c * (-lg) + s * lg, lb + c * (1 - lb) + s * lb, 0, 0,
                0, 0, 0, 1, 0});
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        final Context c = this;
        LinearLayout r = page("Back", "Video settings");
        TextView intro = Ui.text(c, "Changes how the camera looks on this phone only.", 13, Ui.MUTED, false);
        intro.setPadding(0, Ui.dp(c, 10), 0, 0);
        r.addView(intro);

        LinearLayout card = Ui.card(c);
        for (int i = 0; i < SL.length; i++) {
            final int k = i;
            LinearLayout row = Ui.row(c);
            row.addView(Ui.text(c, SL_NAME[i], 14, Ui.TEXT, false), Ui.weight(1));
            vals[i] = Ui.text(c, "", 13, Ui.MUTED, false);
            row.addView(vals[i]);
            LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(-1, -2);
            rl.topMargin = Ui.dp(c, i == 0 ? 0 : 12);
            card.addView(row, rl);
            bars[i] = new SeekBar(c);
            bars[i].setMax(SL_RANGE[i][1] - SL_RANGE[i][0]);
            bars[i].setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                public void onProgressChanged(SeekBar s, int v, boolean user) {
                    if (!user) return;
                    p(c).edit().putInt(SL[k], v + SL_RANGE[k][0]).apply();
                    label(k);
                }
                public void onStartTrackingTouch(SeekBar s) { }
                public void onStopTrackingTouch(SeekBar s) { }
            });
            card.addView(bars[i], new LinearLayout.LayoutParams(-1, -2));
        }
        for (int i = 0; i < CK.length; i++) {
            final int k = i;
            boxes[i] = new CheckBox(c);
            boxes[i].setText(CK_NAME[i]);
            boxes[i].setTextColor(Ui.TEXT);
            boxes[i].setOnCheckedChangeListener(new android.widget.CompoundButton.OnCheckedChangeListener() {
                public void onCheckedChanged(android.widget.CompoundButton b, boolean on) {
                    p(c).edit().putBoolean(CK[k], on).apply();
                }
            });
            card.addView(boxes[i]);
        }
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-1, -2);
        cl.topMargin = Ui.dp(c, 12);
        r.addView(card, cl);

        Button reset = Ui.button(c, "Reset", Ui.SURFACE2, Ui.TEXT, 0);
        reset.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { p(c).edit().clear().apply(); load(); }
        });
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-1, -2);
        bl.topMargin = Ui.dp(c, 12);
        r.addView(reset, bl);
        load();
    }

    private void label(int k) {
        int v = p(this).getInt(SL[k], SL_RANGE[k][2]);
        vals[k].setText(v + (SL[k].equals("hue") ? "°" : "%"));
    }

    private void load() {
        SharedPreferences s = p(this);
        for (int i = 0; i < SL.length; i++) {
            bars[i].setProgress(s.getInt(SL[i], SL_RANGE[i][2]) - SL_RANGE[i][0]);
            label(i);
        }
        for (int i = 0; i < CK.length; i++) boxes[i].setChecked(s.getBoolean(CK[i], false));
    }
}
