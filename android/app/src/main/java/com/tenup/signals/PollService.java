package com.tenup.signals;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

/**
 * Foreground service: polls dashboard/data.json every 90 seconds and
 * raises a high-priority Android notification for every signal the cloud
 * scanner publishes (compared by signal timestamp, so nothing is repeated).
 *
 * First run marks all existing signals as already-seen, so you only get
 * notified about signals that arrive AFTER you installed the app.
 */
public class PollService extends Service {

    private static final String DATA_URL =
            "https://umarmaaz601-rgb.github.io/future-trading-signals/data.json";
    private static final long POLL_MS = 90_000L;
    private static final String CH_SIGNALS = "signals";
    private static final String CH_SCANNER = "scanner";

    private Thread worker;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createChannels();
        startForeground(7, ongoing("starting..."));
        if (worker == null || !worker.isAlive()) {
            worker = new Thread(this::loop, "signal-poll");
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (worker != null) {
            worker.interrupt();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void loop() {
        while (!Thread.currentThread().isInterrupted()) {
            try {
                checkOnce();
            } catch (Throwable ignored) {
                // network hiccup / bad payload - just try again next cycle
            }
            try {
                Thread.sleep(POLL_MS);
            } catch (InterruptedException e) {
                break;
            }
        }
    }

    private void checkOnce() throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(DATA_URL).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(20000);
        c.setRequestProperty("Cache-Control", "no-store");
        InputStream in = c.getInputStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            bos.write(buf, 0, n);
        }
        in.close();
        c.disconnect();
        JSONObject root = new JSONObject(bos.toString("UTF-8"));

        JSONArray arr = root.optJSONArray("signals");
        SharedPreferences sp = getSharedPreferences("sigpoll", MODE_PRIVATE);
        long last = sp.getLong("last_ts", 0L);

        if (last == 0L) {
            // first ever run: swallow the existing history, start clean
            long max = System.currentTimeMillis() / 1000L;
            if (arr != null) {
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject s = arr.optJSONObject(i);
                    if (s != null) {
                        max = Math.max(max, s.optLong("ts", 0L));
                    }
                }
            }
            sp.edit().putLong("last_ts", max).apply();
            syncOutcomes(arr, sp, true);        // swallow TP/SL history too
            updateOngoing(root, "live - " + (arr == null ? 0 : arr.length())
                    + " signals loaded");
            return;
        }

        int fresh = 0;
        if (arr != null) {
            for (int i = arr.length() - 1; i >= 0; i--) {   // oldest first
                JSONObject s = arr.optJSONObject(i);
                if (s == null) {
                    continue;
                }
                long ts = s.optLong("ts", 0L);
                if (ts > last) {
                    postSignal(s, ts);
                    fresh++;
                    last = ts;
                }
            }
        }
        if (fresh > 0) {
            sp.edit().putLong("last_ts", last).apply();
        }
        int oc = syncOutcomes(arr, sp, false);
        updateOngoing(root, "live - updated " + root.optString("updated", "?")
                + (fresh > 0 ? " - " + fresh + " NEW" : "")
                + (oc > 0 ? " - " + oc + " TP/SL" : ""));
    }

    /**
     * Compare every signal's "outcome" field (TP1/TP2/TP3/SL sequence)
     * against the last one we saw; on a change raise a notification.
     * First run just stores the map so old results never notify.
     */
    private int syncOutcomes(JSONArray arr, SharedPreferences sp,
                             boolean firstRun) {
        int changed = 0;
        try {
            JSONObject outs = new JSONObject(sp.getString("outcomes", "{}"));
            boolean dirty = false;
            if (arr != null) {
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject s = arr.optJSONObject(i);
                    if (s == null) continue;
                    String out = s.optString("outcome", "");
                    if (out.isEmpty()) continue;
                    String key = s.optString("symbol", "?") + "|"
                            + s.optLong("ts", 0L);
                    if (out.equals(outs.optString(key, ""))) continue;
                    outs.put(key, out);
                    dirty = true;
                    if (!firstRun) {
                        postOutcome(s, out);
                        changed++;
                    }
                }
            }
            if (dirty || firstRun) {
                sp.edit().putString("outcomes", outs.toString()).apply();
            }
        } catch (Exception ignored) {
            // never let the outcome map break the poller
        }
        return changed;
    }

    /** Notification for a TP/SL result (replaces the previous one for
     *  the same signal, so TP1 -> TP1->TP2 updates in place). */
    private void postOutcome(JSONObject s, String out) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        boolean sl = out.contains("SL");
        boolean fin = s.optBoolean("outcome_final", false);
        String title = (sl ? "❌ SL hit — " : "🎯 TP hit — ")
                + s.optString("symbol", "?");
        StringBuilder body = new StringBuilder(out)
                .append(fin ? "   (final)" : "   (running)")
                .append("\nEntry ").append(fmt(s.optDouble("entry")))
                .append("   SL ").append(fmt(s.optDouble("stop_loss")));
        JSONArray tp = s.optJSONArray("take_profits");
        if (tp != null && tp.length() > 0) {
            body.append("\nTP1 ").append(fmt(tp.optDouble(0)));
        }
        if (tp != null && tp.length() > 1) {
            body.append("   TP2 ").append(fmt(tp.optDouble(1)));
        }
        if (tp != null && tp.length() > 2) {
            body.append("   TP3 ").append(fmt(tp.optDouble(2)));
        }
        long ts = s.optLong("ts", System.currentTimeMillis() / 1000L);
        PendingIntent pi = PendingIntent.getActivity(this, (int) ts,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(this, CH_SIGNALS)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle(title)
                .setContentText(out)
                .setStyle(new Notification.BigTextStyle()
                        .bigText(body.toString()))
                .setContentIntent(pi)
                .setWhen(System.currentTimeMillis())
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_REMINDER)
                .build();
        nm.notify("outcome",
                s.optString("symbol", "?").hashCode() ^ (int) ts, n);
    }

    private void postSignal(JSONObject s, long ts) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        boolean lng = "LONG".equals(s.optString("side"));
        String prob = "";
        if (!s.isNull("prob")) {
            prob = String.format(Locale.US, " - P(1:2) %d%%",
                    Math.round(100 * s.optDouble("prob", 0)));
        }
        String title = (lng ? "\uD83D\uDFE2 LONG  " : "\uD83D\uDD34 SHORT  ")
                + s.optString("symbol", "?") + "   " + s.optString("grade", "");

        JSONArray tp = s.optJSONArray("take_profits");
        StringBuilder body = new StringBuilder();
        body.append("Entry ").append(fmt(s.optDouble("entry")))
                .append("   SL ").append(fmt(s.optDouble("stop_loss")));
        if (tp != null && tp.length() > 0) {
            body.append("\nTP1 ").append(fmt(tp.optDouble(0)));
        }
        if (tp != null && tp.length() > 1) {
            body.append("   TP2 ").append(fmt(tp.optDouble(1)));
        }
        if (tp != null && tp.length() > 2) {
            body.append("   TP3 ").append(fmt(tp.optDouble(2)));
        }
        body.append("\n").append(s.optInt("leverage")).append("x - risk ")
                .append(s.optDouble("stop_pct", 0)).append("%").append(prob);

        String firstLine = "Entry " + fmt(s.optDouble("entry"))
                + "   SL " + fmt(s.optDouble("stop_loss"))
                + (tp != null && tp.length() > 0
                    ? "   TP1 " + fmt(tp.optDouble(0)) : "");

        PendingIntent pi = PendingIntent.getActivity(this, (int) ts,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);

        Notification n = new Notification.Builder(this, CH_SIGNALS)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle(title)
                .setContentText(firstLine)
                .setStyle(new Notification.BigTextStyle().bigText(body.toString()))
                .setContentIntent(pi)
                .setWhen(ts * 1000L)
                .setAutoCancel(true)
                .setCategory(Notification.CATEGORY_REMINDER)
                .build();
        nm.notify("sig", (int) ts, n);
    }

    private void updateOngoing(JSONObject root, String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        JSONObject st = root.optJSONObject("stats");
        String body = text + (st != null
                ? " - " + st.optInt("scanned", 0) + " symbols" : "");
        nm.notify("scanner", 7, ongoing(body));
    }

    private Notification ongoing(String text) {
        PendingIntent pi = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CH_SCANNER)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("Signal scanner")
                .setContentText(text)
                .setContentIntent(pi)
                .setOnlyAlertOnce(true)
                .setOngoing(true)
                .build();
    }

    private void createChannels() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        NotificationChannel sig = new NotificationChannel(CH_SIGNALS,
                "Trading signals", NotificationManager.IMPORTANCE_HIGH);
        sig.enableVibration(true);
        sig.setDescription("New LONG/SHORT signals from the cloud scanner");
        NotificationChannel scn = new NotificationChannel(CH_SCANNER,
                "Scanner status", NotificationManager.IMPORTANCE_LOW);
        scn.setDescription("Ongoing 'scanner is live' indicator");
        nm.createNotificationChannel(sig);
        nm.createNotificationChannel(scn);
    }

    private static String fmt(double v) {
        if (!(v > 0)) {
            return "-";
        }
        if (v >= 1000) {
            return String.format(Locale.US, "%.1f", v);
        }
        if (v >= 1) {
            return String.format(Locale.US, "%.3f", v);
        }
        return String.format(Locale.US, "%.5f", v);
    }
}
