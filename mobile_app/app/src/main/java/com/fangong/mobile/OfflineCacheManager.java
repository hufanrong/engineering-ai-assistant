package com.fangong.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 离线缓存管理器
 * 当手机与电脑不在同一网络时，将拍照/语音/文字保存到本地
 * 网络恢复后自动批量上传到电脑端工作台
 */
public class OfflineCacheManager {

    private static final String TAG = "OfflineCache";
    private static final String PREFS_NAME = "FanGongOfflineCache";
    private static final String KEY_PENDING_ITEMS = "pending_items";
    private static final String KEY_LAST_SYNC = "last_sync_time";
    
    private Context context;
    private SharedPreferences prefs;
    private ExecutorService uploadExecutor;
    private Handler mainHandler;
    private boolean isUploading = false;
    private OfflineCacheListener listener;
    private String serverUrl;
    private String serverId;
    
    public interface OfflineCacheListener {
        void onPendingCountChanged(int count);
        void onUploadStarted();
        void onUploadProgress(int uploaded, int total);
        void onUploadComplete(int success, int failed);
        void onUploadError(String message);
    }

    public OfflineCacheManager(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        this.uploadExecutor = Executors.newSingleThreadExecutor();
        this.mainHandler = new Handler(Looper.getMainLooper());
    }
    
    public void setListener(OfflineCacheListener listener) {
        this.listener = listener;
    }
    
    public void setServerUrl(String url) {
        this.serverUrl = url;
    }
    
    public void setServerId(String id) {
        this.serverId = id;
    }
    
    /**
     * 保存待上传的文件到本地缓存
     */
    public String cacheFile(String filePath, String fileName, String fileType, 
                           String projectId, String uploader, String remark) {
        try {
            // 创建缓存目录
            File cacheDir = new File(context.getFilesDir(), "offline_cache");
            if (!cacheDir.exists()) {
                cacheDir.mkdirs();
            }
            
            // 复制文件到缓存目录
            String cacheId = UUID.randomUUID().toString();
            File srcFile = new File(filePath);
            File destFile = new File(cacheDir, cacheId + "_" + fileName);
            
            if (srcFile.exists()) {
                java.io.FileInputStream fis = new java.io.FileInputStream(srcFile);
                java.io.FileOutputStream fos = new java.io.FileOutputStream(destFile);
                byte[] buffer = new byte[4096];
                int len;
                while ((len = fis.read(buffer)) > 0) {
                    fos.write(buffer, 0, len);
                }
                fis.close();
                fos.close();
            }
            
            // 记录到待上传队列
            JSONObject item = new JSONObject();
            item.put("id", cacheId);
            item.put("file_path", destFile.getAbsolutePath());
            item.put("file_name", fileName);
            item.put("file_type", fileType);
            item.put("project_id", projectId != null ? projectId : "");
            item.put("uploader", uploader != null ? uploader : "");
            item.put("remark", remark != null ? remark : "");
            item.put("created_at", System.currentTimeMillis());
            item.put("retry_count", 0);
            if (serverId != null) item.put("server_id", serverId);
            
            addToPendingQueue(item);
            
            Log.d(TAG, "文件已缓存: " + fileName + " (ID: " + cacheId + ")");
            notifyPendingCountChanged();
            
            return cacheId;
        } catch (Exception e) {
            Log.e(TAG, "缓存文件失败", e);
            return null;
        }
    }
    
    /**
     * 保存文字记录到本地缓存
     */
    public String cacheText(String text, String recordType, String projectId, 
                           String uploader, String location) {
        try {
            String cacheId = UUID.randomUUID().toString();
            
            JSONObject item = new JSONObject();
            item.put("id", cacheId);
            item.put("text_content", text);
            item.put("record_type", recordType != null ? recordType : "text");
            item.put("project_id", projectId != null ? projectId : "");
            item.put("uploader", uploader != null ? uploader : "");
            item.put("location", location != null ? location : "");
            item.put("created_at", System.currentTimeMillis());
            item.put("retry_count", 0);
            item.put("is_text", true);
            if (serverId != null) item.put("server_id", serverId);
            
            addToPendingQueue(item);
            
            Log.d(TAG, "文字已缓存: " + (text.length() > 20 ? text.substring(0, 20) + "..." : text));
            notifyPendingCountChanged();
            
            return cacheId;
        } catch (Exception e) {
            Log.e(TAG, "缓存文字失败", e);
            return null;
        }
    }
    
    /**
     * 添加到待上传队列
     */
    private void addToPendingQueue(JSONObject item) {
        try {
            JSONArray queue = getPendingQueue();
            queue.put(item);
            prefs.edit().putString(KEY_PENDING_ITEMS, queue.toString()).apply();
        } catch (Exception e) {
            Log.e(TAG, "添加到队列失败", e);
        }
    }
    
    /**
     * 获取待上传队列
     */
    public JSONArray getPendingQueue() {
        try {
            String json = prefs.getString(KEY_PENDING_ITEMS, "[]");
            return new JSONArray(json);
        } catch (Exception e) {
            return new JSONArray();
        }
    }
    
    /**
     * 获取待上传数量（全部服务器）
     */
    public int getPendingCount() {
        return getPendingQueue().length();
    }
    
    /**
     * 获取指定服务器的待上传数量
     */
    public int getPendingCountForServer(String serverId) {
        return getPendingQueueForServer(serverId).length();
    }
    
    /**
     * 获取指定服务器的待上传队列
     */
    public JSONArray getPendingQueueForServer(String serverId) {
        JSONArray all = getPendingQueue();
        if (serverId == null) return all;
        JSONArray filtered = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            try {
                JSONObject item = all.getJSONObject(i);
                String sid = item.optString("server_id", "");
                if (sid.isEmpty() || sid.equals(serverId)) {
                    filtered.put(item);
                }
            } catch (Exception e) {
                // ignore
            }
        }
        return filtered;
    }
    
    /**
     * 从队列中移除
     */
    private void removeFromQueue(String id) {
        try {
            JSONArray queue = getPendingQueue();
            JSONArray newQueue = new JSONArray();
            for (int i = 0; i < queue.length(); i++) {
                JSONObject item = queue.getJSONObject(i);
                if (!item.getString("id").equals(id)) {
                    newQueue.put(item);
                }
            }
            prefs.edit().putString(KEY_PENDING_ITEMS, newQueue.toString()).apply();
        } catch (Exception e) {
            Log.e(TAG, "从队列移除失败", e);
        }
    }
    
    /**
     * 检查电脑端是否可达
     */
    public boolean isServerReachable() {
        if (serverUrl == null || serverUrl.isEmpty()) {
            return false;
        }
        try {
            URL url = new URL(serverUrl + "/api/status");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(3000);
            conn.setReadTimeout(3000);
            conn.setRequestMethod("GET");
            int code = conn.getResponseCode();
            conn.disconnect();
            return code == 200;
        } catch (Exception e) {
            return false;
        }
    }
    
    /**
     * 检查是否有网络连接
     */
    public boolean hasNetworkConnection() {
        ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Network network = cm.getActiveNetwork();
            if (network == null) return false;
            NetworkCapabilities caps = cm.getNetworkCapabilities(network);
            return caps != null && (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) 
                                  || caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR));
        } else {
            return cm.getActiveNetworkInfo() != null && cm.getActiveNetworkInfo().isConnected();
        }
    }
    
    /**
     * 开始上传所有待缓存的文件
     */
    public void startUpload() {
        if (isUploading) {
            Log.d(TAG, "已有上传任务在进行");
            return;
        }
        
        int count = getPendingCountForServer(serverId);
        if (count == 0) {
            Log.d(TAG, "当前服务器没有待上传的文件");
            return;
        }
        
        if (!hasNetworkConnection()) {
            Log.d(TAG, "无网络连接，等待网络恢复");
            return;
        }
        
        isUploading = true;
        if (listener != null) {
            mainHandler.post(() -> listener.onUploadStarted());
        }
        
        uploadExecutor.execute(() -> {
            JSONArray queue = getPendingQueueForServer(serverId);
            int success = 0;
            int failed = 0;
            int total = queue.length();
            
            for (int i = 0; i < total; i++) {
                try {
                    JSONObject item = queue.getJSONObject(i);
                    boolean result = uploadItem(item);
                    if (result) {
                        success++;
                        removeFromQueue(item.getString("id"));
                        // 删除缓存文件
                        if (item.has("file_path")) {
                            File f = new File(item.getString("file_path"));
                            if (f.exists()) f.delete();
                        }
                    } else {
                        failed++;
                        // 增加重试次数
                        item.put("retry_count", item.getInt("retry_count") + 1);
                    }
                    
                    if (listener != null) {
                        final int uploaded = i + 1;
                        mainHandler.post(() -> listener.onUploadProgress(uploaded, total));
                    }
                } catch (Exception e) {
                    failed++;
                    Log.e(TAG, "上传项失败", e);
                }
            }
            
            isUploading = false;
            prefs.edit().putLong(KEY_LAST_SYNC, System.currentTimeMillis()).apply();
            
            final int finalSuccess = success;
            final int finalFailed = failed;
            mainHandler.post(() -> {
                if (listener != null) {
                    listener.onUploadComplete(finalSuccess, finalFailed);
                }
                notifyPendingCountChanged();
            });
        });
    }
    
    /**
     * 上传单个项目
     */
    private boolean uploadItem(JSONObject item) {
        try {
            boolean isText = item.optBoolean("is_text", false);
            String uploadUrl = serverUrl + "/api/mobile/offline-batch-upload";
            
            if (isText) {
                // 文字记录上传
                JSONObject data = new JSONObject();
                data.put("text", item.getString("text_content"));
                data.put("record_type", item.optString("record_type", "text"));
                data.put("project_id", item.optString("project_id", ""));
                data.put("uploader", item.optString("uploader", ""));
                data.put("location", item.optString("location", ""));
                data.put("created_at", item.getLong("created_at"));
                
                return postJson(uploadUrl, data.toString());
            } else {
                // 文件上传
                String filePath = item.getString("file_path");
                File file = new File(filePath);
                if (!file.exists()) {
                    Log.w(TAG, "缓存文件不存在: " + filePath);
                    return false;
                }
                
                return uploadFile(uploadUrl, file, 
                    item.optString("file_name", file.getName()),
                    item.optString("file_type", "file"),
                    item.optString("project_id", ""),
                    item.optString("uploader", ""),
                    item.optString("remark", ""));
            }
        } catch (Exception e) {
            Log.e(TAG, "上传项异常", e);
            return false;
        }
    }
    
    /**
     * POST JSON数据
     */
    private boolean postJson(String urlStr, String json) {
        try {
            URL url = new URL(urlStr);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(30000);
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            
            try (OutputStream os = conn.getOutputStream()) {
                os.write(json.getBytes("UTF-8"));
            }
            
            int code = conn.getResponseCode();
            conn.disconnect();
            return code == 200;
        } catch (Exception e) {
            Log.e(TAG, "POST JSON失败", e);
            return false;
        }
    }
    
    /**
     * 上传文件（multipart/form-data）
     */
    private boolean uploadFile(String urlStr, File file, String fileName, 
                              String fileType, String projectId, String uploader, String remark) {
        String boundary = "*****" + System.currentTimeMillis() + "*****";
        String LINE_FEED = "\r\n";
        
        try {
            URL url = new URL(urlStr);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(60000);
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "multipart/form-data;boundary=" + boundary);
            conn.setDoOutput(true);
            conn.setDoInput(true);
            
            try (OutputStream os = conn.getOutputStream()) {
                // 文件字段
                os.write(("--" + boundary + LINE_FEED).getBytes());
                os.write(("Content-Disposition: form-data; name=\"file\"; filename=\"" + fileName + "\"" + LINE_FEED).getBytes());
                os.write(("Content-Type: application/octet-stream" + LINE_FEED).getBytes());
                os.write(LINE_FEED.getBytes());
                
                try (FileInputStream fis = new FileInputStream(file)) {
                    byte[] buffer = new byte[8192];
                    int len;
                    while ((len = fis.read(buffer)) > 0) {
                        os.write(buffer, 0, len);
                    }
                }
                os.write(LINE_FEED.getBytes());
                
                // 其他字段
                addFormField(os, boundary, "file_name", fileName);
                addFormField(os, boundary, "file_type", fileType);
                addFormField(os, boundary, "project_id", projectId);
                addFormField(os, boundary, "uploader", uploader);
                addFormField(os, boundary, "remark", remark);
                
                os.write(("--" + boundary + "--" + LINE_FEED).getBytes());
            }
            
            int code = conn.getResponseCode();
            conn.disconnect();
            return code == 200;
        } catch (Exception e) {
            Log.e(TAG, "上传文件失败", e);
            return false;
        }
    }
    
    private void addFormField(OutputStream os, String boundary, String name, String value) throws IOException {
        String LINE_FEED = "\r\n";
        os.write(("--" + boundary + LINE_FEED).getBytes());
        os.write(("Content-Disposition: form-data; name=\"" + name + "\"" + LINE_FEED).getBytes());
        os.write(LINE_FEED.getBytes());
        os.write((value != null ? value : "").getBytes("UTF-8"));
        os.write(LINE_FEED.getBytes());
    }
    
    /**
     * 注册网络变化监听器
     */
    public void registerNetworkListener() {
        ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return;
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            NetworkRequest request = new NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build();
            
            cm.registerNetworkCallback(request, new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                    Log.d(TAG, "网络已连接，检查是否有待上传文件");
                    // 延迟2秒，等网络稳定
                    mainHandler.postDelayed(() -> {
                        if (isServerReachable()) {
                            startUpload();
                        }
                    }, 2000);
                }
                
                @Override
                public void onLost(Network network) {
                    Log.d(TAG, "网络已断开");
                }
            });
        }
    }
    
    private void notifyPendingCountChanged() {
        if (listener != null) {
            mainHandler.post(() -> listener.onPendingCountChanged(getPendingCount()));
        }
    }
    
    /**
     * 获取上次同步时间
     */
    public String getLastSyncTime() {
        long time = prefs.getLong(KEY_LAST_SYNC, 0);
        if (time == 0) return "从未同步";
        java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
        return sdf.format(new java.util.Date(time));
    }
    
    /**
     * 清空所有缓存（谨慎使用）
     */
    public void clearAllCache() {
        JSONArray queue = getPendingQueue();
        for (int i = 0; i < queue.length(); i++) {
            try {
                JSONObject item = queue.getJSONObject(i);
                if (item.has("file_path")) {
                    File f = new File(item.getString("file_path"));
                    if (f.exists()) f.delete();
                }
            } catch (Exception e) {
                // ignore
            }
        }
        prefs.edit().remove(KEY_PENDING_ITEMS).apply();
        notifyPendingCountChanged();
    }
}
