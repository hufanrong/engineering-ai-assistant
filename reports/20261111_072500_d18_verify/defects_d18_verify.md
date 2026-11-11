# D18 实机验收 · 四条口径逐条实测

| 项 | 值 |
|---|---|
| 检验时间 | 2026-11-11 07:15 – 07:25 |
| 检验版本 | **v0.1.232**（commit `d3cb449`）—— 开发端**尚未**推 D18 修复，验的就是当前线上这版 |
| 机器 | 老板本机 Windows，端口 8756 |
| 结论 | **四条全不达标**，其中第 2 条（核心项）确认「整台消失」 |
| 附件 | `logs/restart.log`、`logs/restart_helper.log`、`logs/restart_canary.log.MISSING.txt`、`logs/restart_result.json.MISSING.txt` |

---

## 一、逐条结论

| # | 验收口径 | 实测 | 判定 |
|---|---|---|---|
| 1 | 点一次重启，30 秒内 `/api/status` 可用且 PID 已变 | 接口返回后 **5.2 秒服务消失**，45 秒内 15 次采样全部不可达，PID `16876 → []` | **不达标** |
| 2 | 制造起不来的情况，**旧进程仍活着、工作台照常可用** | 先把 `app/main.py` 改名（新进程必崩），再点重启：旧 PID `11276` 被杀，端口空，`/api/status` 不可达（45 秒内 1 次可用 / 15 次不可达） | **不达标（整台消失）** |
| 3 | `updates/restart.log` 有本次记录，失败写清原因 | `restart.log` **一次新记录都没有**（最后一条仍是 10-25 与 11-10 14:39 的历史条目）；`restart_helper.log` 只有一行「helper 启动」，无失败原因 | **不达标** |
| 4 | 服务停掉时 `GET /api/update/restart/status` 能读到上次结果 | 服务停着：`HTTP=000`（连接被拒）；服务起着：**`HTTP=404 Not Found`** —— `main.py` 里只注册了 `POST /api/update/restart`，**没有这个 GET 路由**；`restart_result.json` 从未生成 | **不达标** |

---

## 二、根因：helper 用 `taskkill /T` 杀了自己

`app/auto_updater.py` 里 helper 脚本：

```python
def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20)

def main():
    log("helper 启动，目标 PID=%s PORT=%s" % (PIDS, PORT))
    time.sleep(1.5)
    for pid in PIDS:
        if kill_tree(pid):
            killed.append(pid)
            log("已结束 PID=%s" % pid)      # ← 这一行从来没出现过
```

而 helper 是这样被拉起的（同文件 `restart_service()`）：

```python
subprocess.Popen([sys.executable, helper_path], cwd=WORKSPACE_ROOT,
                 creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS, ...)
```

**`Popen` 创建的是子进程；`DETACHED_PROCESS` 只脱离控制台，不脱离进程树。**
于是：

```
服务 PID=11276
  └─ helper PID=xxxxx      ← Popen 出来的子进程
       执行 taskkill /PID 11276 /T /F
       /T = 连同子进程一起杀
       → 杀掉 11276，同时杀掉自己
```

helper 死在 `kill_tree()` 这一句上，所以：
- `restart_helper.log` 永远停在「helper 启动」这一行；
- 后面的「端口释放=…」「已拉起新进程」「重启成功，新 PID=…」全部不会执行；
- `restart_result.json` 永远不会被写。

**这不是"起了但慢"，是"根本没执行到第二步"。**

### 证据：三次调用，三次都停在同一个位置

```
=== 2026-11-10 21:19:36 派发重启 helper ===
[2026-11-10 21:19:36] helper 启动，目标 PID=[21604] PORT=8756

=== 2026-11-11 07:16:54 派发重启 helper ===
[2026-11-11 07:16:55] helper 启动，目标 PID=[16876] PORT=8756

=== 2026-11-11 07:18:42 派发重启 helper ===
[2026-11-11 07:18:43] helper 启动，目标 PID=[11276] PORT=8756
```

三条记录，全部只有「启动」，没有「已结束 PID=」。

---

## 三、第 2 条的完整实测过程（核心项）

这条以前从没验过：**失败时旧服务必须还活着**。

```
【基线】PID [11276] | version 0.1.232
【注入故障】app/main.py → app/main.py.bak  (存在: True)
【故障注入后】当前服务仍可用: True | PID [11276]     ← 旧进程确实还在跑（模块已加载）
【重启接口】{"ok":true,"verified":false,"mode":"helper",
             "will_kill":[11276],"port":8756}
  t=1.0s   PID=[11276]  /api/status=可用
  t=44.0s  PID=[]       /api/status=不可达

=== 第2条判定 ===
旧 PID=11276 | 结束时端口 PID=[] | /api/status=不可达
旧进程存活: False
工作台照常可用: False
可用采样/不可达采样: 1 / 15
```

期望：旧进程活着、工作台照常可用。
实际：**旧进程被杀，工作台消失。**

值得注意的是 —— 「新进程起不来」这个前提**被正确地制造出来了**（`app/main.py` 已改名，
新进程必然 `ImportError` 退出）。但产品并没有因此"回滚到旧进程"，
而是**先把旧的杀了再说**，等于没有任何保护。

`app/main.py` 已在 `finally` 块里还原，`git status` 干净，服务已恢复（v0.1.232 / 62 文件）。

---

## 四、修复建议

### R1 · 先起后死，顺序不能反（治第 1、2 条）

现在的顺序是「杀旧 → 起新 → 等新占端口」。
**必须先起新、确认健康、再杀旧**：

1. 用**另一个端口**（如 8757）临时拉起新进程，等它 `/api/status` 通；
2. 通了 → 再杀旧的、把端口让出来（或者让新的直接接管）；
3. 不通 → **直接放弃，旧进程毫发无损**，写一条失败结果。

只有这样，第 2 条才可能过。**做不到先起后死，就不要杀。**

### R2 · helper 必须离开被杀进程树（治根因）

`taskkill /T` 是"连同子树一起杀"，而 helper 就是子树里的一员。三选一：

| 方案 | 做法 | 评价 |
|---|---|---|
| A（最小改动） | helper 用 `taskkill /PID <pid> /F`，**去掉 `/T`** | 服务是单进程（uvicorn 单 worker），不需要 `/T`；但要确认没有残留子进程 |
| B（更稳） | 用 WMI 创建进程：`Win32_Process.Create`，父进程是 `WmiPrvSE` 而非服务 | helper 彻底不在树里，最干净 |
| C | `CREATE_BREAKAWAY_FROM_JOB` + 计划任务拉起 helper | 重，但最强制 |

推荐 **A 先止血、B 做正解**。

### R3 · 失败要有出口（治第 3 条）

`restart.log` 现在**完全没有本次记录**——helper 里的 `log()` 只写
`restart_helper.log`，而 `restart.log` 只在拉起新进程时才被当成 stdout 重定向打开。
**杀进程这一段根本没有日志。**

要求：
1. helper **第一行**就写：自己的 pid、父 pid、要杀的 pid、当前端口占用者；
2. 每一步（kill / 等端口 / 拉起 / 等健康）都写一行，**失败也要写**；
3. helper 用 `try/finally` 包住，异常必须先 `log(traceback)` 再退出；
4. 补充 `restart_canary.log`：新进程启动后立刻写一行「我是新进程 pid=X version=Y」，
   用来区分「根本没起来」和「起来了但没绑上端口」。**这个文件目前从未被创建过。**

### R4 · 状态必须能脱离 HTTP 读取（治第 4 条）

1. `main.py` 补 `@app.get("/api/update/restart/status")` —— **现在压根没这个路由**（404）；
2. 更根本的是：服务死了就读不到。建议加一个**不依赖服务进程**的读取方式：
   - 前端直接读 `updates/restart_result.json`（本地文件，浏览器可通过 `/static` 或专门路由）；
   - 或者提供 `restart_status.py` 命令行：`python workbench/updates/restart_status.py` 直接打印文件内容；
3. `restart_result.json` 必须是**原子写**（先写 `.tmp` 再 rename），否则中途被杀会留下半个文件。

---

## 五、附带发现（不在四条口径内，但需要修）

### 5.1 02:04 那轮自动回测没跑

```
LastRunTime : 2026-11-10 21:04:11  (LastResult=1)
NextRunTime : 2026-11-11 12:04:10
MissedRuns  : 2
```

5 小时节奏断了一拍。原因：`WakeToRun = False`（当时设置的），机器休眠时任务不会唤醒它，
醒来也不补跑。建议 `WakeToRun=True` + 保留 `StartWhenAvailable=True`，
否则夜里这轮永远是空的。

### 5.2 「重启」这条路现在是净损失

v0.1.231：假成功，但服务一直在。
v0.1.232：真宕机，且没有任何日志。

在 R1/R2 修好之前，我已在计划任务启动器里加了 `--no-restart`，
否则每拉来一版新代码就把工作台搞挂一次。

---

## 六、验收复测方式（修好后请按这个跑）

```bash
# 第1条：正常重启
PID0=$(netstat -ano | grep ':8756.*LISTENING' | awk '{print $NF}')
curl -s -X POST http://127.0.0.1:8756/api/update/restart -d '{}'
# 30 秒内重复 curl /api/status，PID 必须变

# 第2条：失败不宕机（核心）
mv workbench/app/main.py workbench/app/main.py.bak
PID0=$(netstat -ano | grep ':8756.*LISTENING' | awk '{print $NF}')
curl -s -X POST http://127.0.0.1:8756/api/update/restart -d '{}'
sleep 40
netstat -ano | grep ':8756.*LISTENING'   # 必须仍能查到，且 PID == PID0
curl -s http://127.0.0.1:8756/api/status # 必须仍可用
mv workbench/app/main.py.bak workbench/app/main.py

# 第3条：日志完整
grep -c "本次重启" workbench/updates/restart.log
cat workbench/updates/restart_helper.log         # 必须有 kill/端口/拉起/健康 四段
cat workbench/updates/restart_canary.log         # 必须存在，含新进程 pid

# 第4条：状态可读
# 先停服务，再读：
curl -s http://127.0.0.1:8756/api/update/restart/status   # 服务停着时也要有结果
python workbench/updates/restart_status.py               # 或这个，不依赖服务
```
