package dev.printwatch;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Small floating live camera shown on top of a screen. Drag it anywhere, tap it to make it bigger or smaller.
 *  Its spot and size are remembered. Polls /snapshot.jpg only while the screen is in front. */
final class CamPip {
    private static final ExecutorService NET = Executors.newSingleThreadExecutor();
    private final Activity a;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final FrameLayout box;
    private final ImageView img;
    private boolean running;
    private String etag;

    private CamPip(Activity a) {
        this.a = a;
        img = new ImageView(a);
        img.setScaleType(ImageView.ScaleType.CENTER_CROP);
        img.setBackgroundColor(Color.BLACK);
        box = new FrameLayout(a);
        box.setBackground(Ui.box(a, Color.BLACK, Ui.LINE, 12));
        box.setClipToOutline(true);
        box.setElevation(Ui.dp(a, 10));
        box.addView(img, new FrameLayout.LayoutParams(-1, -1));
        box.setOnTouchListener(new View.OnTouchListener() {
            float dx, dy, sx, sy;
            public boolean onTouch(View v, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        dx = v.getX() - e.getRawX(); dy = v.getY() - e.getRawY(); sx = e.getRawX(); sy = e.getRawY();
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        place(e.getRawX() + dx, e.getRawY() + dy);
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (Math.abs(e.getRawX() - sx) < Ui.dp(a, 8) && Math.abs(e.getRawY() - sy) < Ui.dp(a, 8)) {
                            p().edit().putBoolean("big", !p().getBoolean("big", false)).apply();
                            size();
                        }
                        p().edit().putFloat("x", v.getX()).putFloat("y", v.getY()).apply();
                        return true;
                }
                return false;
            }
        });
    }

    private SharedPreferences p() { return a.getSharedPreferences("campip", Activity.MODE_PRIVATE); }

    private void size() {
        int w = Ui.dp(a, p().getBoolean("big", false) ? 260 : 150);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(w, w * 9 / 16, Gravity.TOP | Gravity.START);
        box.setLayoutParams(lp);
        box.post(new Runnable() { public void run() { place(box.getX(), box.getY()); } });
    }

    private void place(float x, float y) {
        View parent = (View) box.getParent();
        if (parent == null) return;
        int m = Ui.dp(a, 8);
        box.setX(Math.max(m, Math.min(x, parent.getWidth() - box.getWidth() - m)));
        box.setY(Math.max(m, Math.min(y, parent.getHeight() - box.getHeight() - m)));
    }

    /** Call from onResume. */
    static CamPip show(Activity a) {
        ViewGroup content = (ViewGroup) a.findViewById(android.R.id.content);
        if (content == null) return null;
        final CamPip c = new CamPip(a);
        content.addView(c.box);
        c.size();
        final float x = c.p().getFloat("x", -1), y = c.p().getFloat("y", -1);
        content.post(new Runnable() {
            public void run() {
                View par = (View) c.box.getParent();
                if (par == null) return;
                c.place(x >= 0 ? x : par.getWidth() - c.box.getWidth() - Ui.dp(c.a, 12),
                        y >= 0 ? y : par.getHeight() - c.box.getHeight() - Ui.dp(c.a, 24));
            }
        });
        VideoFxActivity.apply(a, c.img);
        c.img.setScaleX(Math.signum(c.img.getScaleX()));   // keep colors and flips, skip zoom in the small window
        c.img.setScaleY(Math.signum(c.img.getScaleY()));
        c.running = true;
        c.poll();
        return c;
    }

    /** Call from onPause. */
    void hide() {
        running = false;
        ViewGroup g = (ViewGroup) box.getParent();
        if (g != null) g.removeView(box);
    }

    private void poll() {
        if (!running) return;
        NET.execute(new Runnable() {
            public void run() {
                Bitmap bmp = null;
                boolean ok = false;
                try {
                    Api.Resp r = Api.get(a, "/snapshot.jpg", etag, 8000);
                    if (r.code == 200 && r.body != null) {
                        BitmapFactory.Options o = new BitmapFactory.Options();
                        o.inSampleSize = 2;                       // small window, half-size frame is plenty
                        bmp = BitmapFactory.decodeByteArray(r.body, 0, r.body.length, o);
                        etag = r.etag;
                        ok = true;
                    } else if (r.code == 304) ok = true;
                } catch (Exception ignored) { }
                final Bitmap fb = bmp;
                final boolean fok = ok;
                ui.post(new Runnable() {
                    public void run() {
                        if (!running) return;
                        if (fb != null) img.setImageBitmap(fb);
                        ui.postDelayed(new Runnable() { public void run() { poll(); } }, fok ? 1000 : 3000);
                    }
                });
            }
        });
    }
}
