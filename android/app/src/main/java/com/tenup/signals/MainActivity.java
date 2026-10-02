package com.tenup.signals;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.KeyEvent;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * Minimal shell around the mobile dashboard (GitHub Pages).
 * v1.1: starts PollService, which pops a real Android notification for
 * every new signal the cloud scanner publishes.
 */
public class MainActivity extends Activity {

    private static final String DASHBOARD_URL =
            "https://umarmaaz601-rgb.github.io/future-trading-signals/";

    private WebView web;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setBuiltInZoomControls(false);
        web.setWebViewClient(new WebViewClient());

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(DASHBOARD_URL);
        }

        // --- notification permission (Android 13+) ---
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
        }

        // --- keep the poller ticking while the screen is off (ask once) ---
        new Handler(Looper.getMainLooper()).postDelayed(this::maybeAskBattery, 1500);

        // --- start the signal poller ---
        try {
            startForegroundService(new Intent(this, PollService.class));
        } catch (Exception ignored) {
            // older OEMs may refuse; the dashboard still works
        }
    }

    private void maybeAskBattery() {
        SharedPreferences prefs = getSharedPreferences("sigpoll", MODE_PRIVATE);
        if (prefs.getBoolean("asked_battery", false)) {
            return;
        }
        prefs.edit().putBoolean("asked_battery", true).apply();
        try {
            PowerManager pm = getSystemService(PowerManager.class);
            if (pm != null && !pm.isIgnoringBatteryOptimizations(getPackageName())) {
                startActivity(new Intent(
                        Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:" + getPackageName())));
            }
        } catch (Exception ignored) {
            // no battery dialog available on this device - polling continues,
            // just possibly slower while the screen is off
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
