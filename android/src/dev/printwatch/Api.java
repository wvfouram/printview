package dev.printwatch;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.Charset;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Phone <-> Pi, nothing in between.
 * At home: plain HTTP to the Pi's LAN address.
 * Away: HTTPS straight to your home's public address, trusting ONLY your Pi's
 * certificate (pinned at pairing) and sending this phone's private key.
 * The app pairs itself automatically the first time it reaches the Pi on home Wi-Fi.
 */
final class Api {
    static final String DEFAULT = "http://10.0.0.43:8080";
    private static final Charset UTF8 = Charset.forName("UTF-8");

    private static volatile String mode;        // "lan" | "remote" | null
    private static volatile long modeAt;
    private static volatile long lastSync;
    private static SSLSocketFactory pinnedFactory;
    private static String pinnedFp;

    // ---------------------------------------------------------------- settings
    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("printwatch", Context.MODE_PRIVATE);
    }

    static String lan(Context c) {
        return prefs(c).getString("server", DEFAULT);
    }

    static void setBase(Context c, String url) {
        url = url.trim();
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "http://" + url;
        while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
        prefs(c).edit().putString("server", url).apply();
        reset();
    }

    static boolean paired(Context c) {
        SharedPreferences p = prefs(c);
        return p.getString("token", null) != null && p.getString("fp", null) != null;
    }

    static String remoteBase(Context c) {
        SharedPreferences p = prefs(c);
        String h = p.getString("rhost", null);
        if (h == null) return null;
        // Tailscale Funnel: standard HTTPS port with a real public certificate
        if (h.endsWith(".ts.net")) return "https://" + h;
        return "https://" + h + ":" + p.getInt("rport", 8443);
    }

    static void forgetPairing(Context c) {
        prefs(c).edit().remove("token").remove("fp").remove("rhost").remove("rport").apply();
        reset();
    }

    static void reset() {
        mode = null;
        modeAt = 0;
    }

    /** Current effective base URL (for display). */
    static String base(Context c) {
        return "remote".equals(mode) && remoteBase(c) != null ? remoteBase(c) : lan(c);
    }

    static String modeLabel(Context c) {
        if ("remote".equals(mode)) return "Away · encrypted · " + prefs(c).getString("rhost", "?");
        if ("lan".equals(mode)) return "Home Wi-Fi · " + lan(c).replace("http://", "");
        return "Connecting...";
    }

    // ---------------------------------------------------------------- routing
    private static String resolve(Context c) {
        long now = System.currentTimeMillis();
        String m = mode;
        if (m != null && now - modeAt < 20000) return m;
        String pick;
        if (probeLan(c)) {
            pick = "lan";
            if (!paired(c) || now - lastSync > 600000) {
                lastSync = now;
                try { syncPairing(c); } catch (Exception ignored) { }
            }
        } else if (paired(c) && remoteBase(c) != null) {
            pick = "remote";
        } else {
            pick = "lan";
        }
        mode = pick;
        modeAt = now;
        return pick;
    }

    private static boolean probeLan(Context c) {
        try {
            HttpURLConnection h = (HttpURLConnection) new URL(lan(c) + "/api/ping").openConnection();
            h.setConnectTimeout(1500);
            h.setReadTimeout(2000);
            int code = h.getResponseCode();
            h.disconnect();
            return code == 200;
        } catch (Exception e) {
            return false;
        }
    }

    /** On home Wi-Fi: get a device key once, and keep the Pi's public address + certificate up to date. */
    private static void syncPairing(Context c) throws Exception {
        SharedPreferences p = prefs(c);
        JSONObject j;
        if (!paired(c)) {
            String name = (Build.MANUFACTURER + " " + Build.MODEL).trim();
            j = new JSONObject(raw(c, lan(c) + "/api/pair", "POST",
                    new JSONObject().put("name", name).toString(), false).text());
            if (!j.optBoolean("ok")) return;
            p.edit().putString("token", j.getString("token")).apply();
        } else {
            j = new JSONObject(raw(c, lan(c) + "/api/remote", "GET", null, false).text());
        }
        SharedPreferences.Editor e = p.edit();
        if (!j.isNull("fingerprint")) e.putString("fp", j.optString("fingerprint"));
        if (!j.isNull("host") && !j.optString("host").isEmpty()) e.putString("rhost", j.optString("host"));
        e.putInt("rport", j.optInt("port", 8443));
        e.putString("rinfo", j.toString());
        e.apply();
    }

    // ---------------------------------------------------------------- requests
    static final class Resp {
        int code;
        byte[] body;
        String etag;
        String text() { return body == null ? "" : new String(body, UTF8); }
    }

    static Resp get(Context c, String path, String ifNoneMatch, int timeoutMs) throws Exception {
        return call(c, path, "GET", null, ifNoneMatch, timeoutMs);
    }

    static Resp post(Context c, String path, String json) throws Exception {
        return call(c, path, "POST", json, null, 15000);
    }

    private static Resp call(Context c, String path, String method, String json, String etag, int timeout) throws Exception {
        String m = resolve(c);
        boolean remote = "remote".equals(m);
        String base = remote ? remoteBase(c) : lan(c);
        try {
            return open(c, base + path, method, json, etag, timeout, remote);
        } catch (IOException e) {
            reset();     // network changed: re-probe next time
            throw e;
        }
    }

    private static Resp raw(Context c, String url, String method, String json, boolean remote) throws Exception {
        return open(c, url, method, json, null, 6000, remote);
    }

    private static Resp open(Context c, String url, String method, String json, String etag, int timeout,
                             boolean remote) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(url).openConnection();
        if (remote) secure(c, (HttpsURLConnection) h);
        h.setConnectTimeout(Math.min(timeout, remote ? 8000 : 4000));
        h.setReadTimeout(timeout);
        h.setUseCaches(false);
        if (etag != null) h.setRequestProperty("If-None-Match", etag);
        if (json != null) {
            h.setDoOutput(true);
            h.setRequestMethod(method);
            h.setRequestProperty("Content-Type", "application/json");
            byte[] b = json.getBytes(UTF8);
            h.setFixedLengthStreamingMode(b.length);
            OutputStream o = h.getOutputStream();
            o.write(b);
            o.close();
        } else if (!"GET".equals(method)) {
            h.setRequestMethod(method);
        }
        Resp r = new Resp();
        try {
            r.code = h.getResponseCode();
            r.etag = h.getHeaderField("ETag");
            InputStream in = r.code >= 400 ? h.getErrorStream() : (r.code == 304 ? null : h.getInputStream());
            if (in != null) {
                ByteArrayOutputStream bo = new ByteArrayOutputStream();
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
                in.close();
                r.body = bo.toByteArray();
            }
        } finally {
            h.disconnect();
        }
        if (remote && r.code == 401) {
            // The Pi no longer knows this phone (e.g. it was removed): pair again next time at home.
            prefs(c).edit().remove("token").apply();
        }
        return r;
    }

    /** Open a streaming connection (big downloads). Caller must disconnect. */
    static HttpURLConnection stream(Context c, String path) throws Exception {
        String m = resolve(c);
        boolean remote = "remote".equals(m);
        HttpURLConnection h = (HttpURLConnection) new URL((remote ? remoteBase(c) : lan(c)) + path).openConnection();
        if (remote) secure(c, (HttpsURLConnection) h);
        h.setConnectTimeout(8000);
        h.setReadTimeout(60000);
        return h;
    }

    // ---------------------------------------------------------------- certificate pinning
    private static void secure(Context c, HttpsURLConnection h) throws Exception {
        String fp = prefs(c).getString("fp", null);
        String token = prefs(c).getString("token", null);
        if (fp == null || token == null) throw new IOException("not paired");
        h.setRequestProperty("Authorization", "Bearer " + token);
        if (h.getURL().getHost().endsWith(".ts.net")) return;   // normal certificate check (Tailscale's real cert)
        h.setSSLSocketFactory(factory(fp));
        h.setHostnameVerifier(new HostnameVerifier() {
            // The certificate itself is pinned below, so the host name doesn't matter
            // (your public IP changes; the Pi's key doesn't).
            public boolean verify(String host, SSLSession s) { return true; }
        });
        h.setRequestProperty("Authorization", "Bearer " + token);
    }

    private static synchronized SSLSocketFactory factory(final String fp) throws Exception {
        if (pinnedFactory != null && fp.equals(pinnedFp)) return pinnedFactory;
        TrustManager tm = new X509TrustManager() {
            public void checkClientTrusted(X509Certificate[] chain, String a) throws CertificateException {
                throw new CertificateException("client certs not used");
            }

            public void checkServerTrusted(X509Certificate[] chain, String a) throws CertificateException {
                if (chain == null || chain.length == 0) throw new CertificateException("no certificate");
                try {
                    byte[] d = MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                    StringBuilder sb = new StringBuilder();
                    for (byte x : d) sb.append(String.format("%02x", x));
                    if (!sb.toString().equalsIgnoreCase(fp)) throw new CertificateException("not your Pi");
                } catch (CertificateException e) {
                    throw e;
                } catch (Exception e) {
                    throw new CertificateException(e);
                }
            }

            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(null, new TrustManager[]{tm}, new SecureRandom());
        pinnedFactory = ctx.getSocketFactory();
        pinnedFp = fp;
        return pinnedFactory;
    }
}
