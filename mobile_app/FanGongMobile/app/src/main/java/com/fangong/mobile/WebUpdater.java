package com.fangong.mobile;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * v1.6.0：手机端网页前端资源自动更新。
 *
 * 原理：
 * - 手机端APP内置 assets/index.html（随APK打包，无法热更新）
 * - 启动时（或手动"检查更新"）后台请求电脑端工作台 /api/mobile/web
 *   拿到最新手机网页（含版本号），与本地缓存版本比较
 * - 有新版 → 下载保存到 filesDir/fangong_web/index.html
 * - WebView 加载顺序：本地缓存版优先，无缓存才用 assets 内置版
 *
 * 效果：手机端界面/功能更新无需重装APK，连上电脑（同一网络）即自动更新。
 */
public class WebUpdater {

    private static final String TAG = "WebUpdater";
    private static final String CACHE_DIR = "fangong_web";
    private static final String CACHE_FILE = "index.html";

    private final Context context;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    public interface UpdateCallback {
        void onResult(boolean updated, String newVersion, String oldVersion, String error);
    }

    public WebUpdater(Context context) {
        this.context = context.getApplicationContext();
    }

    /**
     * 获取本地缓存网页的路径（存在则返回，不存在返回null）
     */
    public String getCachedWebPath() {
        File f = getCacheFile();
        return (f != null && f.exists()) ? f.getAbsolutePath() : null;
    }

    /**
     * 本地缓存网页的版本号（无缓存返回 null）
     */
    public String getCachedVersion() {
        File f = getCacheFile();
        if (f == null || !f.exists()) return null;
        try (FileInputStream fis = new FileInputStream(f)) {
            byte[] buf = new byte[8192];
            int n = fis.read(buf);
            String head = new String(buf, 0, n, StandardCharsets.UTF_8);
            return extractVersion(head);
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 后台检查并更新（从电脑端工作台拉取最新手机网页）
     * @param serverBaseUrl 电脑端地址，如 http://192.168.1.100:8756
     * @param callback 结果回调（主线程）
     */
    public void checkAndUpdate(final String serverBaseUrl, final UpdateCallback callback) {
        if (serverBaseUrl == null || serverBaseUrl.isEmpty()) {
            if (callback != null) callback.onResult(false, null, null, "未配置电脑端");
            return;
        }
        new Thread(() -> {
            try {
                String urlStr = serverBaseUrl.replaceAll("/+$", "") + "/api/mobile/web";
                URL url = new URL(urlStr);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);
                conn.setRequestProperty("User-Agent", "FanGongMobile-WebUpdater");

                int code = conn.getResponseCode();
                if (code != 200) {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(false, null, null, "电脑端返回 HTTP " + code));
                    }
                    return;
                }

                InputStream is = conn.getInputStream();
                StringBuilder sb = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(is, StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) sb.append(line);
                }

                JSONObject obj = new JSONObject(sb.toString());
                if (!obj.optBoolean("ok", false)) {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(false, null, null, obj.optString("error", "更新接口异常")));
                    }
                    return;
                }

                String newVersion = obj.optString("version", "0.0.0");
                String html = obj.optString("html", "");

                if (html.isEmpty()) {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(false, null, null, "网页内容为空"));
                    }
                    return;
                }

                String oldVersion = getCachedVersion();
                boolean newer = compareVersions(newVersion, oldVersion) > 0;

                if (!newer) {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(false, newVersion, oldVersion, null));
                    }
                    return;
                }

                // 保存到缓存
                boolean saved = saveToCache(html);
                if (saved) {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(true, newVersion, oldVersion, null));
                    }
                } else {
                    if (callback != null) {
                        mainHandler.post(() -> callback.onResult(false, null, oldVersion, "缓存写入失败"));
                    }
                }
            } catch (Exception e) {
                Log.w(TAG, "checkAndUpdate error: " + e.getMessage());
                if (callback != null) {
                    mainHandler.post(() -> callback.onResult(false, null, null, e.getMessage()));
                }
            }
        }).start();
    }

    private boolean saveToCache(String html) {
        try {
            File dir = new File(context.getFilesDir(), CACHE_DIR);
            if (!dir.exists()) dir.mkdirs();
            File f = new File(dir, CACHE_FILE);
            try (FileOutputStream fos = new FileOutputStream(f)) {
                fos.write(html.getBytes(StandardCharsets.UTF_8));
                fos.flush();
            }
            return true;
        } catch (Exception e) {
            Log.e(TAG, "saveToCache error: " + e.getMessage());
            return false;
        }
    }

    private File getCacheFile() {
        File dir = new File(context.getFilesDir(), CACHE_DIR);
        return new File(dir, CACHE_FILE);
    }

    private String extractVersion(String htmlHead) {
        if (htmlHead == null) return "0.0.0";
        try {
            Pattern p = Pattern.compile("FANGONG_WEB_VERSION\\s*=\\s*\"([^\"]+)\"");
            Matcher m = p.matcher(htmlHead);
            if (m.find()) return m.group(1);
        } catch (Exception ignored) {
        }
        return "0.0.0";
    }

    /**
     * 版本比较：v1 > v2 返回1，相等0，小于-1。null视为0.0.0
     */
    private int compareVersions(String v1, String v2) {
        String a = (v1 == null || v1.isEmpty()) ? "0.0.0" : v1.replaceAll("[^0-9.]", "");
        String b = (v2 == null || v2.isEmpty()) ? "0.0.0" : v2.replaceAll("[^0-9.]", "");
        String[] pa = a.split("\\.");
        String[] pb = b.split("\\.");
        int len = Math.max(pa.length, pb.length);
        for (int i = 0; i < len; i++) {
            int x = i < pa.length ? parseIntSafe(pa[i]) : 0;
            int y = i < pb.length ? parseIntSafe(pb[i]) : 0;
            if (x > y) return 1;
            if (x < y) return -1;
        }
        return 0;
    }

    private int parseIntSafe(String s) {
        try {
            return Integer.parseInt(s);
        } catch (Exception e) {
            return 0;
        }
    }
}
