package dev.printwatch;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ClipDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

/** Shared look: deep graphite, soft cards, amber accent. */
final class Ui {
    static final int BG = Color.parseColor("#0a0b0d");
    static final int SURFACE = Color.parseColor("#15171a");
    static final int SURFACE2 = Color.parseColor("#1f2226");
    static final int LINE = Color.parseColor("#272a30");
    static final int TEXT = Color.parseColor("#f3f1ec");
    static final int MUTED = Color.parseColor("#8d929b");
    static final int FAINT = Color.parseColor("#5a5f68");
    static final int ACCENT = Color.parseColor("#ffb224");
    static final int OK = Color.parseColor("#34d399");
    static final int DANGER = Color.parseColor("#ff5d55");
    static final int INFO = Color.parseColor("#60a5fa");
    static final Typeface MONO = Typeface.MONOSPACE;
    static final Typeface MEDIUM = Typeface.create("sans-serif-medium", Typeface.NORMAL);
    static final Typeface LIGHT = Typeface.create("sans-serif-light", Typeface.NORMAL);
    static final Typeface REGULAR = Typeface.create("sans-serif", Typeface.NORMAL);

    static int dp(Context c, float v) {
        return (int) (v * c.getResources().getDisplayMetrics().density + 0.5f);
    }

    static int alpha(int color, float a) {
        return (Math.round(a * 255) << 24) | (color & 0x00ffffff);
    }

    static GradientDrawable box(Context c, int fill, int stroke, float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, radiusDp));
        if (stroke != 0) g.setStroke(dp(c, 1), stroke);
        return g;
    }

    /** Background with a touch ripple. */
    static Drawable press(Context c, int fill, int stroke, float radiusDp) {
        return new RippleDrawable(ColorStateList.valueOf(Color.parseColor("#26ffffff")),
                box(c, fill, stroke, radiusDp), box(c, Color.WHITE, 0, radiusDp));
    }

    static LinearLayout card(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setBackground(box(c, SURFACE, 0, 20));
        int p = dp(c, 16);
        l.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(c, 12);
        l.setLayoutParams(lp);
        return l;
    }

    static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setTypeface(bold ? MEDIUM : REGULAR);
        t.setIncludeFontPadding(false);
        t.setLineSpacing(0, 1.15f);
        return t;
    }

    /** Numbers that don't jump around as digits change. */
    static TextView num(Context c, String s, float sp, int color, Typeface tf) {
        TextView t = text(c, s, sp, color, false);
        t.setTypeface(tf);
        t.setFontFeatureSettings("tnum");
        return t;
    }

    static TextView heading(Context c, String s) {
        TextView t = text(c, s.toUpperCase(), 11.5f, MUTED, true);
        t.setLetterSpacing(0.1f);
        return t;
    }

    static Button button(Context c, String s, int fill, int textColor, int stroke) {
        Button b = new Button(c);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setTypeface(MEDIUM);
        b.setTextColor(textColor);
        b.setBackground(press(c, fill, stroke, 16));
        b.setStateListAnimator(null);
        b.setMinHeight(dp(c, 54));
        b.setMinimumHeight(dp(c, 54));
        return b;
    }

    /** Round icon button. */
    static ImageView iconButton(Context c, String icon, int color, int fill) {
        ImageView v = new ImageView(c);
        v.setImageDrawable(Icons.of(c, icon, color, 22));
        v.setScaleType(ImageView.ScaleType.CENTER);
        v.setBackground(press(c, fill, 0, 99));
        v.setClickable(true);
        return v;
    }

    static void icon(Button b, String icon, int color) {
        Context c = b.getContext();
        b.setCompoundDrawablesRelative(icon == null ? null : Icons.of(c, icon, color, 20), null, null, null);
        b.setCompoundDrawablePadding(dp(c, 8));
        b.setGravity(Gravity.CENTER);
    }

    static ProgressBar bar(Context c, int color) {
        ProgressBar p = new ProgressBar(c, null, android.R.attr.progressBarStyleHorizontal);
        p.setMax(1000);
        GradientDrawable track = box(c, SURFACE2, 0, 99);
        GradientDrawable fillD = box(c, Color.WHITE, 0, 99);
        LayerDrawable ld = new LayerDrawable(new Drawable[]{track, new ClipDrawable(fillD, Gravity.START, ClipDrawable.HORIZONTAL)});
        ld.setId(0, android.R.id.background);
        ld.setId(1, android.R.id.progress);
        p.setProgressDrawable(ld);
        p.setProgressTintList(ColorStateList.valueOf(color));
        p.setLayoutParams(new LinearLayout.LayoutParams(-1, dp(c, 8)));
        return p;
    }

    static View space(Context c, int dpH) {
        View v = new View(c);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, dp(c, dpH)));
        return v;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        return l;
    }

    static LinearLayout.LayoutParams weight(float w) {
        return new LinearLayout.LayoutParams(0, -2, w);
    }

    static String mins(double m) {
        if (m < 0) return "--";
        int h = (int) (m / 60), mm = (int) (m % 60);
        return h > 0 ? h + "h " + (mm < 10 ? "0" : "") + mm + "m" : mm + "m";
    }
}
