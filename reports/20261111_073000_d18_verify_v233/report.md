# D18 四条验收口径 · v0.1.233 实机复验 —— 四条全部达标

- **版本**：v0.1.233（HEAD `5e0a3f6`，修复提交 `b045341`）
- **时间**：2026-11-11 07:21 ~ 07:30
- **对照**：上一份 `reports/20261111_072500_d18_verify`（v0.1.232，四条全不达标）
- **结论**：**四条全部达标。第 2 条（失败时旧服务必须存活）为本轮核心，历史首次通过。**
- **服务最终状态**：v0.1.233 在线，PID 15668，62 文件 / 1669 向量，`/api/status` 正常

---

## 一、验收对照表

| # | 验收口径 | v0.1.232（d3cb449） | v0.1.233（b045341） | 判定 |
|---|---|---|---|---|
| 1 | 点一次重启，30s 内 `/api/status` 可用且 PID 已变 | 5.2s 后不可达，45s 内 15 次采样全失败，PID `16876 → []` | 旧 `21612` → 新 `15668`，**总耗时 10.7s** | **达标** |
| 2 | **注入起不来后重启，旧进程须活着、工作台须可用** | 旧 PID `11276` 被杀，端口空，45s 内可用 1/15 | 45 次采样 **45 次可用 / 0 次不可达**，旧 PID `15668` **未变** | **达标（首次）** |
| 3 | `updates/restart.log` 有本次完整记录，失败写清原因 | 零记录（末条仍是 10-25 / 11-10 14:39 历史） | 四段齐全，含「探活失败：新代码起不来。旧服务保持原样，本次不重启」 | **达标** |
| 4 | 服务停着也能读到上次重启结果 | 路由未注册，`404`；停服时 `HTTP=000` | `HTTP 200`，`known=true`、`service_alive_now=true`、`result_age_seconds=10.2` | **达标** |

---

## 二、逐条证据

### 第 1 条 · 正常重启

`POST /api/update/restart` → helper `tag=20261111_072606_21612`

```
[07:26:06] helper 启动 目标旧进程=[21612] 端口=8756
[07:26:06] 探活：端口=40801 数据目录=...\_probe_data_20261111_072606_21612
[07:26:11] 探活结果=True 耗时=5.3s version=0.1.233
[07:26:12] 已结束旧进程 PID=21612（未使用 /T，helper 自身不受影响）
[07:26:12] 端口 8756 释放=True 仍占用=[]
[07:26:12] 第 1 次拉起正式实例（端口 8756）
[07:26:17] 第 1 次结果 ok=True 耗时=4.5s pid=[15668] version=0.1.233
[07:26:17] 重启成功：旧=[21612] 新=[15668] 版本=0.1.233 总耗时=10.7s
```

要点：**先在临时端口 40801 + 临时数据目录把新代码跑起来并探活通过，才动手杀旧进程**。这是 v0.1.233 的核心改动（`guarantee: canary_verified_before_kill`）。

### 第 2 条 · 核心：新代码起不来时旧服务必须活着

```
【基线】PID [15668] version 0.1.233
【注入故障】app/main.py → main.py.bak
【注入后】服务仍可用: True  PID [15668]
t=3s  PID=[15668] 可用 v0.1.233
t=6s  PID=[15668] 可用 v0.1.233
...
t=45s PID=[15668] 可用 v0.1.233

=== 第2条（核心）===
旧进程存活: True
工作台照常可用: True
可用/不可达采样: 45 / 0
判定: 达标
【恢复】app/main.py 已还原: True
```

同期 helper 日志（失败路径，旧服务未被触碰）：

```
[07:26:37] helper 启动 目标旧进程=[15668] 端口=8756
[07:26:37] 探活：端口=5282 数据目录=...\_probe_data_20261111_072637_15668
[07:27:24] 探活结果=False 耗时=46.7s version=None
[07:27:24] 探活失败：新代码起不来。**旧服务保持原样，本次不重启**
```

`restart_canary.log` 记到了真实原因：

```
--- spawn ...\venv\Scripts\python.exe ...\start.py (2026-11-11 07:26:37) ---
启动自检失败：程序代码可能不完整（自动更新后常见）。
错误： ModuleNotFoundError: No module named 'app.main'
```

**这条是这轮最关键的一条，也是历史上从没验过的一条。以前的表现是「整台消失」，现在是「旧服务毫发无损」。**

### 第 3 条 · 日志完整性

`updates/restart.log` 本次四段：

1. `helper 启动 argv=... cwd=... pid=21476`
2. `目标旧进程=[15668] 端口=8756 tag=20261111_072637_15668`
3. `探活：端口=5282 数据目录=...`
4. `探活结果=False 耗时=46.7s` → `探活失败：新代码起不来。旧服务保持原样，本次不重启`

`updates/restart_result.json`：

```json
{"ok": false, "phase": "canary",
 "error": "新代码在探活端口 5282 上 45s 内没能应答 /api/status，旧服务未被动过（工作台仍可用）。请查看 updates/restart_canary.log",
 "canary_port": 5282, "canary_last": {"_err": "<urlopen error timed out>"},
 "old_alive": [15668], "guarantee": "canary_verified_before_kill",
 "elapsed": 46.8, "tag": "20261111_072637_15668", "port": 8756}
```

### 第 4 条 · 重启结果查询接口

`GET /api/update/restart/status` → **HTTP 200**

```json
{"ok": false, "phase": "canary",
 "error": "新代码在探活端口 5282 上 45s 内没能应答 /api/status，旧服务未被动过（工作台仍可用）。",
 "canary_port": 5282, "canary_log": "D:\\fangong-workbench\\workbench\\updates\\restart_canary.log",
 "old_alive": [15668], "guarantee": "canary_verified_before_kill", "elapsed": 46.8,
 "tag": "20261111_072637_15668",
 "known": true, "service_alive_now": true, "result_age_seconds": 10.2}
```

---

## 三、v0.1.232 → v0.1.233 的根因与修法（给开发端核对）

**v0.1.232 根因**：helper 由服务用 `subprocess.Popen(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS)` 创建，**只脱离控制台，不脱离进程树**，仍是服务的子进程。helper 执行 `taskkill /PID <服务pid> /T /F`，`/T` 连带杀子进程 → **helper 杀死自己**，死在 `kill_tree()` 那一句，后续「端口释放 / 拉起新进程 / 写结果文件」全部未执行。三次调用日志都只有一行「helper 启动」，是同一根因。

**v0.1.233 修法**（`updates/restart_service.py`，14626 字节，重启时生成）：

1. **探活前置**：先开临时端口 + 临时数据目录把新代码跑起来，`/api/status` 通了才继续；不通直接放弃，旧进程一根毫毛都不动；
2. **`taskkill` 不带 `/T`**，只杀目标 PID，helper 自己不受影响；
3. 结果统一写 `updates/restart_result.json`，并注册 `GET /api/update/restart/status` 读取。

---

## 四、我方两次误判的说明（供开发端判断验收可信度）

**误判 1：把「Job 对象回收」误当成「v0.1.233 仍宕机」。**
第一次复验时服务是用 Bash 工具 `run_in_background` 起的，服务进程和本轮 shell 落在同一个 Windows Job 对象里。旧进程一死，整组被回收，看起来就是「整台消失」。
改法：用**计划任务** `FangongAI-StartWorkbench` 在会话外拉起服务（`start_workbench.cmd`，`FANGONG_NO_BROWSER=1`），再复验，第 1 条实际 **10.7s 达标**。
→ 这不是产品缺陷，但**如果开发端在自动化测试里用后台 shell 起服务，会得到同样的假阴性**，建议在测试脚本里写明。

**误判 2：采样循环用浮点比较，永不命中。**
`if elapsed in (2,4,6,...)` 对 `1.1, 2.1, ...` 永不相等，且 `elapsed >= 13` 提前 break，导致只采到 1~2 个点就判「不可达」。
改法：整数计数循环，1..45。

---

## 五、仍未闭合、需要老板或开发端一句话的

| 编号 | 事项 | 状态 |
|---|---|---|
| D19 | 删项目前先关 chroma / 向量库（`WinError 32 data_level0.bin`）、批量 ≤40 一批、清理失败要让报告变红 | **未动**，下一轮主活 |
| D20 | 新扫描车间名 9/10 带废字（`相对室` 等）；真实项目干净是因为 39 个人工指定 | **待老板拍板**：白名单词表自动归类 vs 一律推「待确认」 |
| D13/D15 | 工艺设备表表头行识别，验收口径：台账 ≥600 台、位号非空率 ≥90% | **未修**，台账 614 台位号未入 |
| D21 | 计划任务 `WakeToRun=False`，休眠不唤醒不补跑（02:04 那轮 `MissedRuns=2`） | 建议改 True |
| — | 三个项目待老板逐条点头才能删：`v01201实测项目B`、9 个 `v01201实测_*`、`v182_195236` | 挂起 |

---

## 六、附件

| 文件 | 说明 |
|---|---|
| `logs/restart.log` | 4352 字节，含 07:26:06 成功重启与 07:26:37 失败探活完整记录 |
| `logs/restart_canary.log` | 1302 字节，含 `ModuleNotFoundError: No module named 'app.main'` |
| `logs/restart_helper.log` | 667 字节，三次派发记录 |
| `logs/restart_result.json` | 584 字节，`ok:false / phase:canary / old_alive:[15668]` |
