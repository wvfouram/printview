package dev.printwatch;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

/** Sliced files on the printer's SD card. Tap one to print it. */
public class FilesActivity extends Base {
    private LinearLayout list;
    private TextView status;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout p = page("Live", "Print from SD card");
        Button refresh = Ui.button(this, "Refresh", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        refresh.setTextSize(14);
        refresh.setMinHeight(Ui.dp(this, 44));
        refresh.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { load(true); } });
        p.addView(refresh);
        status = note(p, "Reading the SD card...");
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        p.addView(list);
        note(p, "Files you send from Bambu Studio or OrcaSlicer (Send, or Print over LAN) land on the SD card and show up here.");
        load(false);
    }

    private void load(boolean refresh) {
        status.setText("Reading the SD card...");
        getJson("/api/files" + (refresh ? "?refresh=1" : ""), new Done<JSONObject>() {
            public void run(JSONObject v, String e) {
                list.removeAllViews();
                if (e != null) { status.setText(e); return; }
                JSONArray a = v.optJSONArray("list");
                int n = a == null ? 0 : a.length();
                status.setText(n == 0 ? "No sliced .3mf files on the SD card." : n + " file" + (n == 1 ? "" : "s"));
                for (int i = 0; i < n; i++) list.addView(row(a.optJSONObject(i)));
            }
        });
    }

    private View row(final JSONObject f) {
        Context c = this;
        LinearLayout r = Ui.row(c);
        r.setBackground(Ui.box(c, Ui.SURFACE, Ui.LINE, 14));
        int p = Ui.dp(c, 10);
        r.setPadding(p, p, p, p);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = Ui.dp(c, 8);
        r.setLayoutParams(lp);
        ImageView th = thumb(64, 64);
        r.addView(th);
        image("/api/files/plate.png?plate=1&path=" + q(f.optString("path")), th);
        LinearLayout info = new LinearLayout(c);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(Ui.dp(c, 12), 0, 0, 0);
        TextView t = Ui.text(c, f.optString("title"), 15, Ui.TEXT, true);
        t.setSingleLine(true);
        info.addView(t);
        TextView s = Ui.text(c, f.optString("path") + "\n" + size(f.optLong("size")) + " · " + f.optString("date"), 12, Ui.MUTED, false);
        s.setTypeface(Ui.MONO);
        info.addView(s);
        r.addView(info, Ui.weight(1));
        r.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                Intent it = new Intent(FilesActivity.this, StartActivity.class);
                it.putExtra("path", f.optString("path"));
                it.putExtra("title", f.optString("title"));
                startActivity(it);
            }
        });
        return r;
    }
}
