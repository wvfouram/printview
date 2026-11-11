package dev.printwatch;

import android.content.Context;
import android.os.Bundle;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.DateFormat;
import java.util.Date;

/** Every finished print with its final photo, plus the last 7 days summary. */
public class HistoryActivity extends Base {
    private LinearLayout list;
    private TextView report;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Back", "Print history");
        report = note(p, "Loading...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        getJson("/api/report", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) { report.setText(e); return; }
                JSONArray l = v.optJSONArray("lines");
                StringBuilder sb = new StringBuilder("Last 7 days\n");
                for (int i = 0; l != null && i < l.length(); i++) sb.append(l.optString(i)).append('\n');
                report.setText(sb.toString().trim());
            }
        });
        getJson("/api/history", new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                if (e != null) return;
                JSONArray a = v.optJSONArray("items");
                if (a == null || a.length() == 0) { list.addView(Ui.text(HistoryActivity.this, "Prints show up here when they finish.", 13, Ui.MUTED, false)); return; }
                for (int i = 0; i < a.length(); i++) list.addView(row(a.optJSONObject(i)));
            }
        });
    }

    private LinearLayout row(JSONObject x) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int pd = Ui.dp(c, 10);
        r.setPadding(pd, pd, pd, pd);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        ImageView th = thumb(96, 54);
        r.addView(th);
        if (!x.isNull("photo")) image("/api/history/photo/" + x.optString("photo"), th);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, 0, 0);
        info.addView(Ui.text(c, x.optString("job"), 15, Ui.TEXT, true));
        String when = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(new Date(x.optLong("end") * 1000L));
        info.addView(Ui.text(c, when + " · " + Ui.mins(x.optDouble("minutes")), 12, Ui.MUTED, false));
        boolean ok = "done".equals(x.optString("result"));
        info.addView(Ui.text(c, ok ? "Finished" : "Failed / stopped", 12, ok ? Ui.OK : Ui.DANGER, false));
        r.addView(info, Ui.weight(1));
        return r;
    }
}
