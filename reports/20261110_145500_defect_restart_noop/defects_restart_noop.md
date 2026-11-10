# 缺陷档案 · 「重启服务」点了没反应，还回 ok:true（D16）

| 项 | 值 |
|---|---|
| 报告时间 | 2026-11-10 14:55 |
| 被测版本 | `0.1.230`（commit `e2b85c7`） |
| 接口 | `POST /api/update/restart` |
| 现象 | 返回 `{"ok":true,"message":"服务已重新启动…","killed_pids":[]}`，**实际一个进程都没换** |
| 严重度 | 高 —— 用户以为换了，还在跑旧代码；且系统**主动说谎** |

---

## 一、怎么发现的

v0.1.231 更新后，服务还报 `0.1.230`。走官方接口重启：

```bash
curl -X POST http://127.0.0.1:8756/api/update/restart -d '{}'
# {"ok":true,"message":"服务已重新启动（端口 8756），新进程已后台运行",
#  "killed_pids":[],"port":8756}
```

`killed_pids` 是**空数组** —— 一个都没杀。随后连续 5 次、间隔 2 秒探版本，
5 次全是 `0.1.230`。**重启没发生，接口却说成功。**

`workbench/updates/restart.log` 留下了铁证：

```
=== 2026-11-10 14:38:34 重启服务 ===
ERROR:    [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8756):
          [winerror 10048] 通常每个套接字地址(协议/网络地址/端口)只允许使用一次。
```

老进程没死，新进程抢不到端口 → 崩了 → 老进程继续服务。

## 二、根因

`workbench/app/auto_updater.py` · `restart_service()`：

```python
pids = _get_pid_by_port(port)          # 查出监听 8756 的 pid
killed = []
for pid in pids:
    if pid == os.getpid():             # ← 问题在这
        continue                       #   跳过自己
    if _kill_process_tree(pid):
        killed.append(pid)
```

**占用端口的那个进程，就是这个正在处理请求的进程自己。**

`uvicorn` 单进程模式下 `os.getpid()` 恰等于监听 pid，于是循环第一轮就把唯一目标跳过了，
`killed` 恒为空，后面再 `Popen` 一个 `start.py` 自然绑不上端口。

这个判断本意是「别把自己杀了」，实际效果是「永远不重启」，并且因为后面
`Popen` 没有失败回传，接口照样返回 `ok:true`。

## 三、附带问题：说谎比不动更糟

`Popen` 之后没有等待、没有健康检查、没有核对版本，直接返回 `ok:true`。
用户看到「已重新启动」，会以为新版本生效了 —— 这正是本单最危险的地方。

正确做法至少要有：

1. 新进程起来后探 `/api/status`，**比对版本号**；不一致就报失败；
2. `killed_pids` 为空时不能回 `ok:true`，要么明说「无需重启/未能结束旧进程」；
3. 拿不到 pid 时要区分「端口没监听」和「查不到」。

## 四、修复建议

### R1 · 重启必须能杀掉自己（核心）

不能用「跳过自己」实现「别自杀」，得用**先起后死**或**父进程代杀**：

**方案 A（推荐）· 分离的助手进程**

```python
helper = [sys.executable, "-c", _RESTART_HELPER_SRC, str(os.getpid()), str(port)]
subprocess.Popen(helper, cwd=WORKSPACE_ROOT,
                 creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, ...)
# 助手：sleep 1 → taskkill /PID 自己 /T /F → 等端口释放 → 拉起 start.py → 探健康
# 接口：立刻返回 {"ok": True, "restarting": True, "old_pid": 自己}
#       （真正的成功与否由 /api/status 的 version 变化来确认）
```

助手进程独立于服务，杀谁都不影响自己，是唯一稳的解法。

**方案 B · 只有父进程能重启**

记下父 pid（`os.getppid()`），由父进程执行 kill 子 + 起新。
缺点：`start.py` 直接跑时父进程是 shell，未必可控。

**方案 C（不推荐）· 自杀后靠外部拉起**
`os._exit()` 依赖外部守护，脱离了本机已有的计划任务就不成立。

### R2 · 返回值必须诚实

```python
if not killed:
    return {"ok": False, "error": "未能结束占用端口 %d 的进程（pid=%s）" % (port, pids),
            "port_pids": pids, "self_pid": os.getpid()}
```

不要用 `ok:true` 掩盖「什么都没做」。

### R3 · 重启后校验版本

`restart_service()` 结束时探一次 `/api/status`，把 `old_version` / `new_version`
一并返回；两者相同就说明**没换成**，要显式报出来。

### R4 · 顺便看 `_get_pid_by_port` 的容错

`except Exception: pass` 会把「netstat 解不出来」也咽成「端口没人监听」。
至少要记一条日志，否则又是一次静默失败（与 v0.1.229 的扫描吞异常同型）。

## 五、验收

1. 从 `0.1.230` 调重启，10 秒内 `/api/status` 变成新版本；
2. 返回体里 `killed_pids` 非空、带 `old_version`/`new_version`，且两者不同；
3. 新进程绑不上端口时返回 `ok:false` 并带 `WinError 10048` 原文，
   **不许**再出现 `ok:true` + 旧版本仍在服务；
4. 重启过程中 `/api/status` 不可用的时间 ≤ 30 秒；
5. 连续调两次不产生两个服务进程（`netstat` 里 8756 只有一个 LISTENING）。

## 六、复现

```bash
# 1) 记下当前版本
curl -s --noproxy '*' http://127.0.0.1:8756/api/status | python -c "import sys,json;print(json.load(sys.stdin)['version'])"

# 2) 调重启，看 killed_pids 是否为空
curl -s --noproxy '*' -X POST http://127.0.0.1:8756/api/update/restart \
     -H 'Content-Type: application/json' -d '{}'

# 3) 再探版本 —— 若与 1) 相同，缺陷复现
curl -s --noproxy '*' http://127.0.0.1:8756/api/status | python -c "import sys,json;print(json.load(sys.stdin)['version'])"

# 4) 看 restart.log 里有没有 WinError 10048
tail -20 workbench/updates/restart.log
```
