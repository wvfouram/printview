package dev.printwatch;

import android.content.Context;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

import org.json.JSONObject;

/** Start / stop the AMS HT (or AMS 2 Pro) dryer while the printer is idle. */
public class DryActivity extends Base {
    private static final String[] FIL = {"PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PVA"};
    private EditText unit, temp, hours;
    private Spinner fil;
    private CheckBox rotate;
    private TextView status;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        Context c = this;
        LinearLayout p = page("Back", "AMS drying");
        LinearLayout card = Ui.card(c);
        unit = field(card, "AMS number", "129");
        card.addView(Ui.text(c, "Filament", 14, Ui.TEXT, false));
        fil = new Spinner(c);
        fil.setAdapter(new ArrayAdapter<String>(c, android.R.layout.simple_spinner_dropdown_item, FIL));
        card.addView(fil);
        temp = field(card, "Temperature (30-85 °C)", "55");
        hours = field(card, "Hours (1-24)", "4");
        rotate = new CheckBox(c);
        rotate.setText("Rotate spools (pull filament out of the feeders first)");
        rotate.setTextColor(Ui.TEXT);
        rotate.setChecked(true);
        card.addView(rotate);
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-1, -2);
        cl.topMargin = Ui.dp(c, 12);
        p.addView(card, cl);

        Button start = Ui.button(c, "Start drying", Ui.ACCENT, Ui.BG, 0);
        start.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { send(true); } });
        Button stop = Ui.button(c, "Stop drying", Ui.SURFACE2, Ui.TEXT, Ui.LINE);
        stop.setOnClickListener(new View.OnClickListener() { public void onClick(View v) { send(false); } });
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-1, -2);
        bl.topMargin = Ui.dp(c, 12);
        p.addView(start, bl);
        LinearLayout.LayoutParams bl2 = new LinearLayout.LayoutParams(-1, -2);
        bl2.topMargin = Ui.dp(c, 8);
        p.addView(stop, bl2);
        status = note(p, "The printer only allows drying while it's idle. Time left shows on the AMS screen.");
    }

    private EditText field(LinearLayout card, String label, String def) {
        TextView t = Ui.text(this, label, 14, Ui.TEXT, false);
        t.setPadding(0, Ui.dp(this, 8), 0, 0);
        card.addView(t);
        EditText e = new EditText(this);
        e.setInputType(InputType.TYPE_CLASS_NUMBER);
        e.setText(def);
        e.setTextColor(Ui.TEXT);
        card.addView(e);
        return e;
    }

    private void send(boolean on) {
        try {
            JSONObject j = new JSONObject();
            j.put("action", "ams_dry");
            j.put("on", on);
            j.put("unit", Integer.parseInt(unit.getText().toString().trim()));
            j.put("filament", FIL[fil.getSelectedItemPosition()]);
            j.put("temp", Integer.parseInt(temp.getText().toString().trim()));
            j.put("hours", Integer.parseInt(hours.getText().toString().trim()));
            j.put("rotate", rotate.isChecked());
            status.setText(on ? "Starting..." : "Stopping...");
            final boolean fon = on;
            post("/api/cmd", j.toString(), new Done<JSONObject>() {
                public void run(JSONObject v, String e) {
                    status.setText(e != null ? e : fon ? "Drying started" : "Drying stopped");
                }
            });
        } catch (Exception e) {
            status.setText("Check the numbers: " + e.getMessage());
        }
    }
}
