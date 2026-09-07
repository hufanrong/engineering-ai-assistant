package com.fangong.mobile;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * 多服务器管理器
 * 支持添加、删除、切换多个电脑端工作台地址
 */
public class ServerManager {

    private static final String PREFS_NAME = "FanGongServers";
    private static final String KEY_SERVERS = "servers_list";
    private static final String KEY_CURRENT_SERVER = "current_server_id";
    
    private Context context;
    private SharedPreferences prefs;
    
    public static class ServerInfo {
        public String id;
        public String name;
        public String url;
        public String description;
        public long addedAt;
        public long lastConnectedAt;
        
        public ServerInfo(String id, String name, String url, String description) {
            this.id = id;
            this.name = name;
            this.url = url;
            this.description = description != null ? description : "";
            this.addedAt = System.currentTimeMillis();
            this.lastConnectedAt = 0;
        }
        
        public JSONObject toJson() {
            try {
                JSONObject obj = new JSONObject();
                obj.put("id", id);
                obj.put("name", name);
                obj.put("url", url);
                obj.put("description", description);
                obj.put("added_at", addedAt);
                obj.put("last_connected_at", lastConnectedAt);
                return obj;
            } catch (Exception e) {
                return new JSONObject();
            }
        }
        
        public static ServerInfo fromJson(JSONObject obj) {
            try {
                ServerInfo info = new ServerInfo(
                    obj.getString("id"),
                    obj.getString("name"),
                    obj.getString("url"),
                    obj.optString("description", "")
                );
                info.addedAt = obj.optLong("added_at", System.currentTimeMillis());
                info.lastConnectedAt = obj.optLong("last_connected_at", 0);
                return info;
            } catch (Exception e) {
                return null;
            }
        }
    }
    
    public ServerManager(Context context) {
        this.context = context.getApplicationContext();
        this.prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }
    
    /**
     * 获取所有服务器列表
     */
    public List<ServerInfo> getAllServers() {
        List<ServerInfo> list = new ArrayList<>();
        try {
            String json = prefs.getString(KEY_SERVERS, "[]");
            JSONArray arr = new JSONArray(json);
            for (int i = 0; i < arr.length(); i++) {
                ServerInfo info = ServerInfo.fromJson(arr.getJSONObject(i));
                if (info != null) {
                    list.add(info);
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
        return list;
    }
    
    /**
     * 保存服务器列表
     */
    private void saveServers(List<ServerInfo> servers) {
        try {
            JSONArray arr = new JSONArray();
            for (ServerInfo info : servers) {
                arr.put(info.toJson());
            }
            prefs.edit().putString(KEY_SERVERS, arr.toString()).apply();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }
    
    /**
     * 添加服务器
     */
    public ServerInfo addServer(String name, String url, String description) {
        // 规范化URL
        if (!url.startsWith("http")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        
        String id = "server_" + System.currentTimeMillis();
        ServerInfo info = new ServerInfo(id, name, url, description);
        
        List<ServerInfo> servers = getAllServers();
        servers.add(info);
        saveServers(servers);
        
        // 如果是第一个服务器，设为当前
        if (servers.size() == 1) {
            setCurrentServer(id);
        }
        
        return info;
    }
    
    /**
     * 删除服务器
     */
    public boolean removeServer(String id) {
        List<ServerInfo> servers = getAllServers();
        boolean removed = false;
        List<ServerInfo> newList = new ArrayList<>();
        for (ServerInfo info : servers) {
            if (!info.id.equals(id)) {
                newList.add(info);
            } else {
                removed = true;
            }
        }
        
        if (removed) {
            saveServers(newList);
            // 如果删除的是当前服务器，切换到第一个
            String current = getCurrentServerId();
            if (current != null && current.equals(id)) {
                if (newList.size() > 0) {
                    setCurrentServer(newList.get(0).id);
                } else {
                    prefs.edit().remove(KEY_CURRENT_SERVER).apply();
                }
            }
        }
        return removed;
    }
    
    /**
     * 更新服务器信息
     */
    public boolean updateServer(String id, String name, String url, String description) {
        List<ServerInfo> servers = getAllServers();
        for (ServerInfo info : servers) {
            if (info.id.equals(id)) {
                info.name = name;
                info.url = url;
                info.description = description != null ? description : "";
                saveServers(servers);
                return true;
            }
        }
        return false;
    }
    
    /**
     * 获取当前服务器
     */
    public ServerInfo getCurrentServer() {
        String id = getCurrentServerId();
        if (id == null) return null;
        for (ServerInfo info : getAllServers()) {
            if (info.id.equals(id)) {
                return info;
            }
        }
        return null;
    }
    
    /**
     * 获取当前服务器ID
     */
    public String getCurrentServerId() {
        return prefs.getString(KEY_CURRENT_SERVER, null);
    }
    
    /**
     * 设置当前服务器
     */
    public boolean setCurrentServer(String id) {
        List<ServerInfo> servers = getAllServers();
        for (ServerInfo info : servers) {
            if (info.id.equals(id)) {
                info.lastConnectedAt = System.currentTimeMillis();
                saveServers(servers);
                prefs.edit().putString(KEY_CURRENT_SERVER, id).apply();
                return true;
            }
        }
        return false;
    }
    
    /**
     * 获取服务器数量
     */
    public int getServerCount() {
        return getAllServers().size();
    }
    
    /**
     * 检查URL是否已存在
     */
    public boolean isUrlExists(String url) {
        if (!url.startsWith("http")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        for (ServerInfo info : getAllServers()) {
            if (info.url.equalsIgnoreCase(url)) {
                return true;
            }
        }
        return false;
    }
    
    /**
     * 根据URL查找服务器
     */
    public ServerInfo findServerByUrl(String url) {
        for (ServerInfo info : getAllServers()) {
            if (info.url.equalsIgnoreCase(url)) {
                return info;
            }
        }
        return null;
    }
}
