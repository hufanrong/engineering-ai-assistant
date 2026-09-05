# 繁工AI 云端合并主库（v0.1.11）

把多台电脑的本地解析库合并成一个完整云库，手机端在户外也能在线读取。

## 一、服务端部署（任选一台常开主机/服务器）

1. 安装 Python 3.10+（勾选 Add to PATH）。
2. 双击 `run_server.bat`（自动装依赖并启动）。
3. 看到 `Uvicorn running on http://0.0.0.0:8760` 即成功，**保持窗口常开**。
4. 记住本机 IP（`ipconfig` 里 IPv4 地址，如 `192.168.1.50`）。

> 若服务器在公网/公司外网，需在路由器/防火墙放行 8760 端口，并把 `app.py` 顶部 `API_KEY` 改为强密码（默认 `fanGong_cloud_2026` 仅限内网）。

## 二、各电脑工作台对接

打开工作台 `app/config.py`，配置：

```python
CLOUD_ENDPOINT = "http://192.168.1.50:8760"   # 云库地址（改成你的服务器 IP）
CLOUD_API_KEY = "fanGong_cloud_2026"          # 与云端 app.py 的 API_KEY 一致
NODE_NAME = "办公室-张三"                      # 本机名称，云端按节点区分来源
```

保存后重启工作台。解析完成的文件会进入「云端合并上传队列」页，点「上传到云端」即合并到云库（SHA256 自动去重，重复文件跳过）。多台电脑各自上传，云库自动并成一个完整库。

## 三、云端能力

| 地址 | 说明 |
| --- | --- |
| `GET /api/cloud/status` | 云库状态（文件数） |
| `POST /api/parse-nodes/payloads` | 工作台自动上传入口（按 SHA256 去重） |
| `GET /api/cloud/list` | 云库文件清单 |
| `POST /api/cloud/search` | 在线检索（手机端/外部 Agent 读取入口） |
| `GET /api/cloud/export-fglib` | 导出云端完整库 `.fglib` |
| `POST /api/cloud/import-fglib` | 导入工作台导出的 `.fglib` |

## 四、手机端/外部 Agent 使用

手机端 App 配置云库地址 `http://<服务器IP>:8760`，即可调用 `/api/cloud/search` 在线检索全部项目资料（户外可用）。

## 五、双保险

- 云库是各电脑解析结果的**汇总副本**，每台电脑本地库仍完整保留；
- 也可从云库导出 `.fglib`，在任何电脑「库导出合并」导入，即使云端主机故障也能重建。
