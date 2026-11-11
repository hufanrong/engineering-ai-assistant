# WORKbuddy 缺陷报告 20261111_072500_d18_verify

- 状态：**failed（四条口径全不达标）**
- 被测版本：`0.1.232`（commit `d3cb449`）—— **开发端尚未推 D18 修复**，验的就是当前线上这版
- 检验时间：2026-11-11 07:15 – 07:25
- 详细档案：**[`defects_d18_verify.md`](defects_d18_verify.md)**
- 机读证据：[`evidence_d18_verify.json`](evidence_d18_verify.json)
- **日志原件**：[`logs/restart.log`](logs/restart.log)、[`logs/restart_helper.log`](logs/restart_helper.log)、
  [`logs/restart_canary.log.MISSING.txt`](logs/restart_canary.log.MISSING.txt)、
  [`logs/restart_result.json.MISSING.txt`](logs/restart_result.json.MISSING.txt)

## 结论表

| # | 口径 | 实测 | 判定 |
|---|---|---|---|
| 1 | 30 秒内 `/api/status` 可用且 PID 已变 | 接口返回后 **5.2 秒服务消失**，45 秒内 15 次采样全不可达，PID `16876 → []` | 不达标 |
| 2 | **起不来时旧进程仍活着** | 注入 `app/main.py` 改名后点重启：旧 PID `11276` 被杀，端口空，45 秒内 1 次可用 / 15 次不可达 | **不达标（整台消失）** |
| 3 | `restart.log` 有本次记录并写清原因 | `restart.log` **零条新记录**；`restart_helper.log` 每次只有「helper 启动」一行 | 不达标 |
| 4 | 服务停掉时能读到上次重启结果 | 停着：`HTTP=000`；起着：**`HTTP=404`**（该 GET 路由压根没注册）；`restart_result.json` 从未生成 | 不达标 |

## 根因一句话

**helper 用 `taskkill /T` 把包括自己在内的整棵进程树杀了。**

```python
subprocess.Popen([sys.executable, helper_path],
                 creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)   # ← 子进程
...
subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"])                    # ← /T 连子进程一起杀
```

`DETACHED_PROCESS` 只脱离控制台，**不脱离进程树**。helper 是服务的子进程，
所以 `/T` 一执行，服务死、helper 也死，死在 `kill_tree()` 这一句 ——
后面的「等端口释放 / 拉起新服务 / 写 restart_result.json」全部没执行。

三次调用，三次都停在同一个位置：

```
[2026-11-10 21:19:36] helper 启动，目标 PID=[21604] PORT=8756
[2026-11-11 07:16:55] helper 启动，目标 PID=[16876] PORT=8756
[2026-11-11 07:18:43] helper 启动，目标 PID=[11276] PORT=8756
```

**「已结束 PID=」这一行从来没出现过。** 不是"起了但慢"，是"根本没走到第二步"。

## 第 2 条的完整过程（核心项，以前从没验过）

```
【基线】PID [11276] | version 0.1.232
【注入故障】app/main.py → app/main.py.bak
【故障注入后】当前服务仍可用: True | PID [11276]     ← 前提造对了
【重启接口】{"ok":true,"verified":false,"mode":"helper","will_kill":[11276],"port":8756}
  t=1.0s   PID=[11276]  /api/status=可用
  t=44.0s  PID=[]       /api/status=不可达

旧进程存活: False      工作台照常可用: False
```

期望：失败时旧进程活着。实际：**旧进程先被杀，新进程又起不来，两头落空。**
产品没有任何"新起不来就回滚"的保护，顺序是「杀旧 → 起新 → 等新占端口」，
杀在前面，等于先拆房子再试新房子漏不漏。

`app/main.py` 已在 `finally` 里还原，`git status` 干净，服务已恢复到 v0.1.232 / 62 文件。

## 修复要点

1. **R1 先起后死（治 1、2 条）**：新进程先在备用端口（如 8757）起，`/api/status` 通了
   再杀旧的；不通就**直接放弃，旧进程毫发无损**。做不到这句，第 2 条永远过不了。
2. **R2 helper 必须离开被杀进程树（治根因）**：
   - A（最小改动）：`taskkill /PID x /F` **去掉 `/T`** —— 服务是 uvicorn 单进程，不需要 `/T`；
   - B（正解）：用 WMI `Win32_Process.Create` 创建 helper，父进程变成 `WmiPrvSE`，彻底不在树里；
   - C：`CREATE_BREAKAWAY_FROM_JOB` + 计划任务拉起。
3. **R3 日志要有出口（治 3 条）**：helper 首行写自己 pid / 父 pid / 目标 pid / 端口占用者；
   每步一写；`try/finally` 包住，异常先 `log(traceback)` 再退；
   补 `restart_canary.log`（新进程启动即写 pid + version，用来区分"没起来"和"起来了没绑上端口"）。
   **这个 canary 文件至今从未被创建过。**
4. **R4 状态脱离 HTTP（治 4 条）**：`main.py` 补 `GET /api/update/restart/status`（现在只有 POST）；
   `restart_result.json` 原子写（`.tmp` + rename）；再提供 `restart_status.py` 命令行直读文件，
   服务死了也能查。

## 附带发现：02:04 那轮自动回测被跳过

```
LastRunTime : 2026-11-10 21:04:11
NextRunTime : 2026-11-11 12:04:10
MissedRuns  : 2
WakeToRun   : False
```

`WakeToRun=False`，机器休眠时任务不会唤醒，醒来也不补跑，5 小时节奏断档。
建议开 `WakeToRun=True`。

## 当前状态

| 项 | 值 |
|---|---|
| 服务 | v0.1.232 在线，62 文件 / 1669 向量 |
| 工作区 | 干净（`app/main.py` 已还原） |
| 计划任务 | 下次 12:04:10，带 `--no-restart`（D18 未修好前的保险） |
| 日志归档 | `reports/20261111_072500_d18_verify/logs/` |
