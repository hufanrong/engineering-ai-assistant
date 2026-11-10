# WORKbuddy 缺陷报告 20261110_145500_defect_restart_noop

- 状态：**failed**
- 被测版本：`0.1.230`（commit `e2b85c7`）
- 接口：`POST /api/update/restart`
- 详细档案：**[`defects_restart_noop.md`](defects_restart_noop.md)**
- 机读证据：[`evidence_restart_noop.json`](evidence_restart_noop.json)

## 一句话

**「重启服务」返回 `ok:true`，一个进程都没换。** 用户以为新版本生效了，实际还在跑旧代码。

## 实测

```bash
$ curl -X POST http://127.0.0.1:8756/api/update/restart -d '{}'
{"ok":true,"message":"服务已重新启动（端口 8756），新进程已后台运行",
 "killed_pids":[], "port":8756}
```

`killed_pids` 是空数组。随后 5 次探版本（间隔 2 秒）全是 `0.1.230`，
PID 前后都是 `24808` —— 重启没发生。

`workbench/updates/restart.log`：

```
=== 2026-11-10 14:38:34 重启服务 ===
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8756):
       [winerror 10048] 通常每个套接字地址(协议/网络地址/端口)只允许使用一次。
```

老进程没死，新进程抢不到端口崩了，老进程继续对外服务。

## 根因

`workbench/app/auto_updater.py` · `restart_service()`（752-811 行）：

```python
for pid in pids:
    if pid == os.getpid():   # ← 跳过"自己"
        continue
    if _kill_process_tree(pid):
        killed.append(pid)
```

`uvicorn` 单进程模式下，**监听 8756 的那个 PID 就是正在处理这个请求的进程自己**。
于是唯一目标被跳过，`killed` 恒为空，后面 `Popen` 的 `start.py` 自然绑不上端口。

「别把自己杀了」的意图，实现成了「永远不重启」。

## 附带问题：说谎比不动更糟

`Popen` 之后既不等待也不校验，直接 `ok:true`。用户失去判断依据 ——
这正是本单最危险的部分。

## 修复要点

1. **R1（核心）** 分离的助手进程：接口起一个独立 helper（`DETACHED_PROCESS`），
   helper 反过来 `taskkill /T /F` 掉服务再拉起 `start.py`，最后探健康。
   **先起后死**是唯一稳的解 —— helper 不属于服务进程树，杀谁都不影响自己。
2. **R2** `killed` 为空时返回 `ok:false` 并带 `port_pids` / `self_pid`，不许 `ok:true`；
3. **R3** 重启后探 `/api/status`，回传 `old_version` / `new_version`，相同即报「没换成」；
4. **R4** `_get_pid_by_port` 里的 `except Exception: pass` 要留日志 ——
   把「netstat 解析失败」咽成「端口没人监听」又是一次静默失败（与 v0.1.229 扫描吞异常同型）。

## 验收

1. 从 `0.1.230` 调重启，10 秒内 `/api/status` 变成新版本；
2. 返回体 `killed_pids` 非空、带新旧版本号且不同；
3. 新进程绑不上端口时返回 `ok:false` + `WinError 10048` 原文；
4. 重启期间不可用 ≤ 30 秒；
5. 连调两次不产生两个服务进程（8756 只有一个 LISTENING）。

## 这条为什么值得优先修

本机自测循环（`wb_loop.py`）每轮都靠「重启服务」把新代码换上去。
这个接口是假的，意味着**开发端提交的修复，在老板机器上不一定真的生效** ——
版本号看着对、行为还是旧的，后面所有缺陷单都会被它污染。
