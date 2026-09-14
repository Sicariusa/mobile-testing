package com.example.shop;

import android.app.Activity;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Minimal, deterministic login screen used as a live target for the QA runner.
 * Correct credentials (test@example.com / Password123) swap in a Welcome screen;
 * anything else shows an inline error. No network, no persistence.
 */
public class MainActivity extends Activity implements View.OnClickListener {

    static final String VALID_EMAIL = "test@example.com";
    static final String VALID_PASSWORD = "Password123";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);
        findViewById(R.id.login).setOnClickListener(this);
    }

    @Override
    public void onClick(View v) {
        String email = ((EditText) findViewById(R.id.email)).getText().toString().trim();
        String password = ((EditText) findViewById(R.id.password)).getText().toString();
        if (VALID_EMAIL.equals(email) && VALID_PASSWORD.equals(password)) {
            setContentView(welcomeView());
        } else {
            ((TextView) findViewById(R.id.error)).setText("Invalid credentials");
        }
    }

    private View welcomeView() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(48, 48, 48, 48);
        root.addView(bigText("Welcome"));
        root.addView(bigText("PAY NOW"));
        return root;
    }

    private TextView bigText(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(34);
        t.setPadding(0, 24, 0, 24);
        return t;
    }
}
