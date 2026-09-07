package com.fangong.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListAdapter;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.widget.PopupMenu;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.content.FileProvider;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

public class MainActivity extends AppCompatActivity implements OfflineCacheManager.OfflineCacheListener {

    private WebView webView;
    private ValueCallback<Uri[]> filePathCallback;
    private String cameraPhotoPath;
    private static final int FILE_CHOOSER_REQUEST = 1;
    private static final int PERMISSION_REQUEST = 100;
    
    private OfflineCacheManager offlineCache;
    private ServerManager serverManager;
    private ServerManager.ServerInfo currentServer;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        
        requestPermissions();
        
        // 初始化管理器
        serverManager = new ServerManager(this);
        offlineCache = new OfflineCacheManager(this);
        offlineCache.setListener(this);
        offlineCache.registerNetworkListener();
        
        // 创建布局
        LinearLayout rootLayout = new LinearLayout(this);
        rootLayout.setOrientation(LinearLayout.VERTICAL);
        rootLayout.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.MATCH_PARENT
        ));
        
        webView = new WebView(this);
        webView.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.MATCH_PARENT
        ));
        rootLayout.addView(webView);
        setContentView(rootLayout);
        
        setupWebView();
        
        // 标题栏点击显示服务器管理
        if (getSupportActionBar() != null) {
            getSupportActionBar().setDisplayHomeAsUpEnabled(true);
            getSupportActionBar().setHomeAsUpIndicator(android.R.drawable.ic_menu_more);
        }
        
        // 检查是否有已配置的服务器
        currentServer = serverManager.getCurrentServer();
        if (currentServer == null) {
            // 没有服务器，显示添加服务器界面
            showAddServerDialog(true);
        } else {
            connectToServer(currentServer);
        }
    }
    
    private void setupWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(false);
        
        webView.addJavascriptInterface(new NativeBridge(), "AndroidNative");
        
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                view.loadUrl(url);
                return true;
            }
            
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                super.onReceivedError(view, errorCode, description, failingUrl);
                showOfflineMode();
            }
            
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                updateWebOfflineStatus();
            }
        });
        
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> callback, 
                    FileChooserParams fileChooserParams) {
                if (filePathCallback != null) {
                    filePathCallback.onReceiveValue(null);
                }
                filePathCallback = callback;
                
                Intent contentSelectionIntent = new Intent(Intent.ACTION_GET_CONTENT);
                contentSelectionIntent.addCategory(Intent.CATEGORY_OPENABLE);
                contentSelectionIntent.setType("*/*");
                contentSelectionIntent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                
                Intent captureIntent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                if (captureIntent.resolveActivity(getPackageManager()) != null) {
                    File photoFile = createImageFile();
                    if (photoFile != null) {
                        cameraPhotoPath = photoFile.getAbsolutePath();
                        Uri photoUri = FileProvider.getUriForFile(MainActivity.this,
                            getPackageName() + ".fileprovider", photoFile);
                        captureIntent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
                    }
                }
                
                Intent chooserIntent = new Intent(Intent.ACTION_CHOOSER);
                chooserIntent.putExtra(Intent.EXTRA_INTENT, contentSelectionIntent);
                chooserIntent.putExtra(Intent.EXTRA_TITLE, "选择文件");
                chooserIntent.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{captureIntent});
                
                startActivityForResult(chooserIntent, FILE_CHOOSER_REQUEST);
                return true;
            }
        });
    }
    
    /**
     * 连接到指定服务器
     */
    private void connectToServer(ServerManager.ServerInfo server) {
        currentServer = server;
        serverManager.setCurrentServer(server.id);
        offlineCache.setServerUrl(server.url);
        offlineCache.setServerId(server.id);
        
        // 更新标题
        if (getSupportActionBar() != null) {
            getSupportActionBar().setTitle("繁工AI - " + server.name);
            getSupportActionBar().setSubtitle(server.url);
        }
        
        // 从assets加载内置的手机端网页（独立于电脑端网页服务）
        webView.loadUrl("file:///android_asset/index.html");
        
        // 检查是否有待上传文件
        int pending = offlineCache.getPendingCountForServer(server.id);
        if (pending > 0 && offlineCache.isServerReachable()) {
            offlineCache.startUpload();
        }
    }
    
    /**
     * 显示添加/编辑服务器对话框
     * @param isFirst 是否首次添加（首次不可取消）
     * @param editServer 要编辑的服务器，null表示添加新服务器
     */
    private void showAddServerDialog(boolean isFirst, ServerManager.ServerInfo editServer) {
        boolean isEdit = editServer != null;
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle(isEdit ? "编辑电脑" : (isFirst ? "添加电脑端工作台" : "添加新电脑"));
        
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40, 20, 40, 20);
        
        final EditText nameInput = new EditText(this);
        nameInput.setHint("电脑名称（如：办公室电脑、项目部电脑）");
        if (isEdit) nameInput.setText(editServer.name);
        layout.addView(nameInput);
        
        final EditText urlInput = new EditText(this);
        urlInput.setHint("IP地址:端口（如：192.168.1.100:8756）");
        if (isEdit) urlInput.setText(editServer.url.replace("http://", ""));
        layout.addView(urlInput);
        
        final EditText descInput = new EditText(this);
        descInput.setHint("备注（可选）");
        if (isEdit) descInput.setText(editServer.description);
        layout.addView(descInput);
        
        // 错误提示文本
        final TextView errorText = new TextView(this);
        errorText.setTextColor(0xFFEA6668);
        errorText.setTextSize(12);
        errorText.setVisibility(android.view.View.GONE);
        layout.addView(errorText);
        
        builder.setView(layout);
        
        builder.setPositiveButton(isEdit ? "保存" : "添加并连接", null); // 先设null，后面自定义
        
        if (!isFirst || isEdit) {
            builder.setNegativeButton("取消", null);
        }
        
        builder.setCancelable(!isFirst);
        
        final AlertDialog dialog = builder.create();
        dialog.show();
        
        // 自定义确定按钮，避免自动关闭
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String name = nameInput.getText().toString().trim();
            String url = urlInput.getText().toString().trim();
            
            if (name.isEmpty()) name = "电脑" + (serverManager.getServerCount() + 1);
            if (url.isEmpty()) {
                errorText.setText("请输入IP地址和端口");
                errorText.setVisibility(android.view.View.VISIBLE);
                return;
            }
            
            // 规范化URL
            if (!url.startsWith("http")) url = "http://" + url;
            while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
            
            if (isEdit) {
                // 编辑模式
                serverManager.updateServer(editServer.id, name, url, descInput.getText().toString().trim());
                Toast.makeText(this, "已保存修改", Toast.LENGTH_SHORT).show();
                dialog.dismiss();
                // 重新连接
                ServerManager.ServerInfo updated = serverManager.getCurrentServer();
                if (updated != null && updated.id.equals(editServer.id)) {
                    connectToServer(updated);
                } else {
                    // 如果编辑的不是当前服务器，切换过去
                    List<ServerManager.ServerInfo> all = serverManager.getAllServers();
                    for (ServerManager.ServerInfo s : all) {
                        if (s.id.equals(editServer.id)) {
                            connectToServer(s);
                            break;
                        }
                    }
                }
            } else {
                // 添加模式
                if (serverManager.isUrlExists(url)) {
                    errorText.setText("该电脑地址已添加，请直接在列表中选择");
                    errorText.setVisibility(android.view.View.VISIBLE);
                    return;
                }
                
                ServerManager.ServerInfo server = serverManager.addServer(name, url, descInput.getText().toString().trim());
                Toast.makeText(this, "已添加：" + server.name, Toast.LENGTH_SHORT).show();
                dialog.dismiss();
                connectToServer(server);
            }
        });
    }
    
    /**
     * 简化调用：添加新服务器
     */
    private void showAddServerDialog(boolean isFirst) {
        showAddServerDialog(isFirst, null);
    }
    
    /**
     * 显示服务器切换对话框（支持切换、编辑、删除、添加）
     */
    private void showServerSwitchDialog() {
        List<ServerManager.ServerInfo> servers = serverManager.getAllServers();
        if (servers.isEmpty()) {
            showAddServerDialog(true);
            return;
        }
        
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("管理电脑（当前：" + (currentServer != null ? currentServer.name : "无") + "）");
        
        String[] items = new String[servers.size() + 1];
        for (int i = 0; i < servers.size(); i++) {
            ServerManager.ServerInfo s = servers.get(i);
            int pending = offlineCache.getPendingCountForServer(s.id);
            String currentMark = (currentServer != null && currentServer.id.equals(s.id)) ? " ✓" : "";
            items[i] = s.name + "  (" + s.url.replace("http://", "") + ")" + currentMark + (pending > 0 ? "  [待上传:" + pending + "]" : "");
        }
        items[servers.size()] = "➕ 添加新电脑";
        
        builder.setItems(items, (dialog, which) -> {
            if (which < servers.size()) {
                // 长按或点击显示操作菜单
                showServerActionDialog(servers.get(which));
            } else {
                showAddServerDialog(false);
            }
        });
        
        builder.setNegativeButton("关闭", null);
        builder.show();
    }
    
    /**
     * 显示单个服务器的操作菜单（连接/编辑/删除）
     */
    private void showServerActionDialog(ServerManager.ServerInfo server) {
        boolean isCurrent = currentServer != null && currentServer.id.equals(server.id);
        String[] actions = isCurrent 
            ? new String[]{"🔄 重新连接", "✏️ 编辑修改", "🗑️ 删除此电脑"}
            : new String[]{"📡 连接此电脑", "✏️ 编辑修改", "🗑️ 删除此电脑"};
        
        new AlertDialog.Builder(this)
            .setTitle(server.name + "  (" + server.url.replace("http://", "") + ")")
            .setItems(actions, (dialog, which) -> {
                if (which == 0) {
                    // 连接/重新连接
                    connectToServer(server);
                    Toast.makeText(this, "正在连接：" + server.name, Toast.LENGTH_SHORT).show();
                } else if (which == 1) {
                    // 编辑
                    showAddServerDialog(false, server);
                } else if (which == 2) {
                    // 删除
                    new AlertDialog.Builder(this)
                        .setTitle("确认删除")
                        .setMessage("确定要删除电脑「" + server.name + "」吗？\n\n该电脑的离线缓存数据不会被删除，重新添加后仍可继续上传。")
                        .setPositiveButton("删除", (d, w) -> {
                            serverManager.removeServer(server.id);
                            Toast.makeText(this, "已删除：" + server.name, Toast.LENGTH_SHORT).show();
                            // 切换到下一个服务器
                            ServerManager.ServerInfo next = serverManager.getCurrentServer();
                            if (next != null) {
                                currentServer = next;
                                connectToServer(next);
                            } else {
                                currentServer = null;
                                showAddServerDialog(true);
                            }
                        })
                        .setNegativeButton("取消", null)
                        .show();
                }
            })
            .setNegativeButton("返回", null)
            .show();
    }
    

    
    /**
     * JavaScript桥接接口
     */
    public class NativeBridge {
        @android.webkit.JavascriptInterface
        public boolean isOfflineMode() {
            return !offlineCache.isServerReachable();
        }
        
        @android.webkit.JavascriptInterface
        public int getPendingUploadCount() {
            return offlineCache.getPendingCountForServer(currentServer != null ? currentServer.id : null);
        }
        
        @android.webkit.JavascriptInterface
        public String getLastSyncTime() {
            return offlineCache.getLastSyncTime();
        }
        
        @android.webkit.JavascriptInterface
        public void cacheText(String text, String recordType, String projectId, 
                              String uploader, String location) {
            String id = offlineCache.cacheText(text, recordType, projectId, uploader, location);
            if (id != null) {
                runOnUiThread(() -> 
                    Toast.makeText(MainActivity.this, "已保存到离线缓存，联网后自动上传到" + (currentServer != null ? currentServer.name : "电脑"), Toast.LENGTH_SHORT).show()
                );
            }
        }
        
        @android.webkit.JavascriptInterface
        public void cacheFile(String filePath, String fileName, String fileType,
                             String projectId, String uploader, String remark) {
            String id = offlineCache.cacheFile(filePath, fileName, fileType, projectId, uploader, remark);
            if (id != null) {
                runOnUiThread(() -> 
                    Toast.makeText(MainActivity.this, "文件已保存，联网后自动上传到" + (currentServer != null ? currentServer.name : "电脑"), Toast.LENGTH_SHORT).show()
                );
            }
        }
        
        @android.webkit.JavascriptInterface
        public void startSync() {
            if (offlineCache.isServerReachable()) {
                offlineCache.startUpload();
            } else {
                runOnUiThread(() -> 
                    Toast.makeText(MainActivity.this, "当前无法连接" + (currentServer != null ? currentServer.name : "电脑") + "，请检查网络", Toast.LENGTH_SHORT).show()
                );
            }
        }
        
        @android.webkit.JavascriptInterface
        public String getServerUrl() {
            return currentServer != null ? currentServer.url : "";
        }
        
        @android.webkit.JavascriptInterface
        public String getServerName() {
            return currentServer != null ? currentServer.name : "";
        }
        
        @android.webkit.JavascriptInterface
        public int getServerCount() {
            return serverManager.getServerCount();
        }
        
        @android.webkit.JavascriptInterface
        public void switchServer() {
            runOnUiThread(() -> showServerSwitchDialog());
        }
    }
    
    private void updateWebOfflineStatus() {
        int pending = offlineCache.getPendingCountForServer(currentServer != null ? currentServer.id : null);
        boolean offline = !offlineCache.isServerReachable();
        webView.evaluateJavascript(
            "if(window.updateOfflineStatus) { window.updateOfflineStatus(" + offline + ", " + pending + "); }",
            null
        );
    }
    
    private void showOfflineMode() {
        webView.evaluateJavascript(
            "if(window.showOfflineMode) { window.showOfflineMode(); }",
            null
        );
    }
    
    private File createImageFile() {
        try {
            String timeStamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.CHINA).format(new Date());
            String imageFileName = "IMG_" + timeStamp + "_";
            File storageDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES);
            return File.createTempFile(imageFileName, ".jpg", storageDir);
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }
    
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (filePathCallback == null) return;
            
            Uri[] results = null;
            if (resultCode == Activity.RESULT_OK) {
                if (data != null && data.getDataString() != null) {
                    results = new Uri[]{Uri.parse(data.getDataString())};
                } else if (data != null && data.getClipData() != null) {
                    int count = data.getClipData().getItemCount();
                    results = new Uri[count];
                    for (int i = 0; i < count; i++) {
                        results[i] = data.getClipData().getItemAt(i).getUri();
                    }
                } else if (cameraPhotoPath != null) {
                    File file = new File(cameraPhotoPath);
                    if (file.exists()) {
                        results = new Uri[]{Uri.fromFile(file)};
                    }
                }
            }
            
            filePathCallback.onReceiveValue(results);
            filePathCallback = null;
        }
    }
    
    private void requestPermissions() {
        String[] permissions = {
            Manifest.permission.INTERNET,
            Manifest.permission.CAMERA,
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION
        };
        
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions = new String[]{
                Manifest.permission.INTERNET,
                Manifest.permission.CAMERA,
                Manifest.permission.RECORD_AUDIO,
                Manifest.permission.READ_MEDIA_IMAGES,
                Manifest.permission.READ_MEDIA_VIDEO,
                Manifest.permission.READ_MEDIA_AUDIO,
                Manifest.permission.ACCESS_FINE_LOCATION
            };
        }
        
        boolean needRequest = false;
        for (String perm : permissions) {
            if (ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                needRequest = true;
                break;
            }
        }
        
        if (needRequest) {
            ActivityCompat.requestPermissions(this, permissions, PERMISSION_REQUEST);
        }
    }
    
    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
    }
    
    // ========== OfflineCacheListener ==========
    @Override
    public void onPendingCountChanged(int count) {
        updateWebOfflineStatus();
    }
    
    @Override
    public void onUploadStarted() {
        runOnUiThread(() -> 
            Toast.makeText(this, "开始同步数据到" + (currentServer != null ? currentServer.name : "电脑") + "...", Toast.LENGTH_SHORT).show()
        );
    }
    
    @Override
    public void onUploadProgress(int uploaded, int total) {
    }
    
    @Override
    public void onUploadComplete(int success, int failed) {
        runOnUiThread(() -> {
            String msg = "同步到" + (currentServer != null ? currentServer.name : "电脑") + "完成：成功" + success + "项";
            if (failed > 0) msg += "，失败" + failed + "项";
            Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
            updateWebOfflineStatus();
        });
    }
    
    @Override
    public void onUploadError(String message) {
        runOnUiThread(() -> 
            Toast.makeText(this, "同步失败：" + message, Toast.LENGTH_SHORT).show()
        );
    }
    
    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            int pending = offlineCache.getPendingCountForServer(currentServer != null ? currentServer.id : null);
            new AlertDialog.Builder(this)
                .setTitle("退出")
                .setMessage("确定要退出繁工AI吗？\n\n当前电脑：" + (currentServer != null ? currentServer.name : "无") + 
                           "\n待上传：" + pending + " 项")
                .setPositiveButton("退出", (dialog, which) -> finish())
                .setNegativeButton("取消", null)
                .show();
        }
    }
    
    /**
     * 长按标题栏切换服务器（备用方式）
     */
    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            showServerSwitchDialog();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }
    
    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
