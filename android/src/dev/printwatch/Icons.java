package dev.printwatch;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.RectF;
import android.graphics.drawable.Drawable;

/** Small line icons drawn in code on a 24x24 grid (no image files needed). */
final class Icons extends Drawable {
    private final String name;
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int size;

    private Icons(Context c, String name, int color, int sizeDp) {
        this.name = name;
        this.size = Ui.dp(c, sizeDp);
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeCap(Paint.Cap.ROUND);
        stroke.setStrokeJoin(Paint.Join.ROUND);
        stroke.setStrokeWidth(2f);
        stroke.setColor(color);
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(color);
    }

    static Icons of(Context c, String name, int color, int sizeDp) {
        Icons i = new Icons(c, name, color, sizeDp);
        i.setBounds(0, 0, i.size, i.size);
        return i;
    }

    static Icons of(Context c, String name, int color) { return of(c, name, color, 22); }

    @Override public int getIntrinsicWidth() { return size; }
    @Override public int getIntrinsicHeight() { return size; }

    @Override
    public void draw(Canvas cv) {
        android.graphics.Rect b = getBounds();
        float s = Math.min(b.width(), b.height()) / 24f;
        cv.save();
        cv.translate(b.left + (b.width() - 24 * s) / 2f, b.top + (b.height() - 24 * s) / 2f);
        cv.scale(s, s);
        Path p = new Path();
        switch (name) {
            case "pause":
                cv.drawRoundRect(new RectF(6, 5, 10, 19), 1.5f, 1.5f, fill);
                cv.drawRoundRect(new RectF(14, 5, 18, 19), 1.5f, 1.5f, fill);
                break;
            case "play":
                p.moveTo(8, 5); p.lineTo(19, 12); p.lineTo(8, 19); p.close();
                cv.drawPath(p, fill); cv.drawPath(p, stroke);
                break;
            case "stop":
                cv.drawRoundRect(new RectF(6, 6, 18, 18), 2.5f, 2.5f, fill);
                break;
            case "bulb":
            case "bulb_on":
                if (name.equals("bulb_on")) cv.drawCircle(12, 9.5f, 6, fill);
                cv.drawCircle(12, 9.5f, 6, stroke);
                cv.drawLine(9.5f, 18.5f, 14.5f, 18.5f, stroke);
                cv.drawLine(10.5f, 21.5f, 13.5f, 21.5f, stroke);
                break;
            case "expand":
                poly(cv, 4, 9, 4, 4, 9, 4); poly(cv, 15, 4, 20, 4, 20, 9);
                poly(cv, 20, 15, 20, 20, 15, 20); poly(cv, 9, 20, 4, 20, 4, 15);
                break;
            case "close":
                cv.drawLine(6, 6, 18, 18, stroke); cv.drawLine(18, 6, 6, 18, stroke);
                break;
            case "gear":
                cv.drawCircle(12, 12, 3, stroke);
                cv.drawCircle(12, 12, 7, stroke);
                for (int k = 0; k < 8; k++) {
                    double a = Math.PI / 4 * k;
                    cv.drawLine(12 + 7 * (float) Math.cos(a), 12 + 7 * (float) Math.sin(a),
                            12 + 9.5f * (float) Math.cos(a), 12 + 9.5f * (float) Math.sin(a), stroke);
                }
                break;
            case "sliders":
                cv.drawLine(4, 7, 20, 7, stroke); cv.drawLine(4, 12, 20, 12, stroke); cv.drawLine(4, 17, 20, 17, stroke);
                cv.drawCircle(9, 7, 2.6f, fill); cv.drawCircle(15, 12, 2.6f, fill); cv.drawCircle(8, 17, 2.6f, fill);
                break;
            case "layers":
                p.moveTo(12, 4); p.lineTo(20, 8.5f); p.lineTo(12, 13); p.lineTo(4, 8.5f); p.close();
                cv.drawPath(p, stroke);
                poly(cv, 4, 12.5f, 12, 17, 20, 12.5f);
                poly(cv, 4, 16.5f, 12, 21, 20, 16.5f);
                break;
            case "sd":
                p.moveTo(9, 3); p.lineTo(18, 3); p.lineTo(18, 21); p.lineTo(6, 21); p.lineTo(6, 6); p.close();
                cv.drawPath(p, stroke);
                cv.drawLine(10, 7, 10, 9.5f, stroke); cv.drawLine(12.5f, 7, 12.5f, 9.5f, stroke); cv.drawLine(15, 7, 15, 9.5f, stroke);
                break;
            case "film":
                cv.drawRoundRect(new RectF(3, 5.5f, 21, 18.5f), 3, 3, stroke);
                p.moveTo(10, 9); p.lineTo(15, 12); p.lineTo(10, 15); p.close();
                cv.drawPath(p, fill);
                break;
            case "spark":
                p.moveTo(12, 3); p.quadTo(12.8f, 11.2f, 21, 12); p.quadTo(12.8f, 12.8f, 12, 21);
                p.quadTo(11.2f, 12.8f, 3, 12); p.quadTo(11.2f, 11.2f, 12, 3); p.close();
                cv.drawPath(p, fill);
                break;
            case "shield":
                p.moveTo(12, 3); p.lineTo(19.5f, 6); p.lineTo(19.5f, 11.5f);
                p.quadTo(19.5f, 18, 12, 21); p.quadTo(4.5f, 18, 4.5f, 11.5f); p.lineTo(4.5f, 6); p.close();
                cv.drawPath(p, stroke);
                poly(cv, 8.5f, 12, 11, 14.5f, 15.5f, 9.5f);
                break;
            case "chev_r":
                poly(cv, 9, 5, 16, 12, 9, 19);
                break;
            case "chev_l":
                poly(cv, 15, 5, 8, 12, 15, 19);
                break;
            default:
                cv.drawCircle(12, 12, 4, fill);
        }
        cv.restore();
    }

    private void poly(Canvas cv, float... xy) {
        Path p = new Path();
        p.moveTo(xy[0], xy[1]);
        for (int i = 2; i < xy.length; i += 2) p.lineTo(xy[i], xy[i + 1]);
        cv.drawPath(p, stroke);
    }

    @Override public void setAlpha(int a) { stroke.setAlpha(a); fill.setAlpha(a); invalidateSelf(); }
    @Override public void setColorFilter(ColorFilter cf) { stroke.setColorFilter(cf); fill.setColorFilter(cf); }
    @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
}
