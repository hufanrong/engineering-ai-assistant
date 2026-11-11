# v0.1.233 全量自测：11 项失败 → 5 个新缺陷（D22~D26）

- **轮次**：2026-11-11 07:33:24 手动触发，commit `ffd1ac0`，phases `1,2,3,5,6`
- **自测原始报告**：`reports/20261111_073324/`
- **结果**：`status=failed`，**passed 58 / failed 11 / skipped 2**
- **归并后**：11 条失败 = **1 个根因级联 9 条** + **1 条断言与决策冲突** + **1 条并发缺陷**
- **重要前提**：这 11 条不是 11 个独立问题，别按 11 个改。

| 阶段 | 通过 | 失败 | 跳过 |
|---|---|---|---|
| 1 | 10 | 4 | 0 |
| 2 | 9 | 0 | 0 |
| 3 | 7 | 6 | 1 |
| 5 | 9 | 0 | 0 |
| 6 | 23 | 1 | 1 |

专项回归套件：`P23 / F1 / T24`，唯一失败在 `test_restart_really.py`（42 过 / 1 败）。

---

## D23（P0）· 扫描：心跳盲区 + 慢到触发卡死判定

**这是本轮最重的缺陷，也直接关系「能不能实际用在工程项目上」。**

### 事实链

| 时刻 | 事件 |
|---|---|
| 07:33:28 | 自测创建项目 `自测_20261111_073328`，`POST /api/scan` → **200 ok:true**，folders=`data\uploads` |
| 07:33:28 ~ 07:38:29 | **301 秒内 `done=0/0`、`heartbeat` 一次未刷新** → selftest 按 300s 阈值判「卡死」 |
| 07:40:54 | 自测判失败，切回马诺诺 |
| 07:48:28 | `/api/scan/status` → `done=46/63`，仍在跑 |
| 07:53:02 | `done=63/63`，`running=false`；自测项目 `index.json` 落盘 27382 字节 |
| 合计 | **07:33:28 → 07:53:02，约 19.5 分钟** |

**结论：扫描没有死。它慢，而且前 301 秒完全不报进度。**

### 两个独立毛病，得分开修

**① 心跳只覆盖「文件解析完成」这一刻**
`app/scanner.py:764` 的 `cb(done,total,msg)` 只在**一个文件解析完之后**才回调；`app/main.py:243` 的 `progress_cb` 只是把 `status["heartbeat"]` 刷成当前时间，挂在同一个 `cb` 上。
→ 扫描启动、初始化、以及**第一个大文件解析的整个过程，全在心跳盲区里**。
`main.py:277` 的 docstring 自己都写了「63 个真实文件里有 25 张 DWG（每张 ODA 转换约 6 秒）和十几份扫描件 PDF（Tesseract OCR 单页数秒），第一个文件就可能跑上百秒」——**既然知道首个文件可能上百秒，心跳就不该等到它解析完才刷一次。**

**② `total` 初始为 0，界面无法区分「在啃大文件」和「死了」**
`SCAN_STATUS.update({"running": False, "done": 0, "total": 0, ...})` 之后，`total` 要等第一次 `cb` 才有值。这 301 秒里 `/api/scan/status` 返回 `done=0/0`，前端只能显示「0/0」，用户看不出任何东西。

**③（附带）单文件无超时上限**
一个文件卡住就拖死整轮，没有 per-file timeout。

### 我建议的改法

1. `background_scan` 一进来就 `cb(0, total, "开始枚举")`，**先枚举、先把 total 设出来**，再进解析循环；
2. **每个文件开始解析前**打一次心跳（不是解析完才打）：`progress_cb(done, total, "parsing <name>")`；
3. 单文件解析加超时（建议 120s），超时记进 `status["error"]` 并跳过，不中断整轮；
4. 前端把 `heartbeat` 距今秒数显示出来（「正在解析 xxx，已 87 秒」），别只显示 0/0。

**验收口径建议**：65 个真实样本（含 25 DWG + 扫描件 PDF）整轮扫描 ≤ 8 分钟，且**任意 30 秒窗口内 `heartbeat` 至少刷新 1 次**。

---

## D22（P1）· 并发写 `restart_result.json` 静默失败 28~38 次

`test_restart_really.py` 场景 C：8 个真进程 × 60 次 = **480 次并发写**同一个 `restart_result.json`（payload 60KB，放大竞态窗口）。

| 复现 | 结果文件 | `restart.log` 里「写结果失败」条数 | 失败率 |
|---|---|---|---|
| 第 1 次（本轮自测） | 合法单对象 ✅ | **28** | 5.8% |
| 第 2 次（单独复现） | 合法单对象 ✅ | **38** | 7.9% |

- 进程退出码全是 0 —— 因为 `write_result` 用 try/except 把异常吞进 LOG 了，**外部完全看不出失败**。
- 所以断言只能数 `restart.log` 里「写结果失败」的条数，这也是它判红的原因。

### 为什么这条要紧（不只是测试红了）

1. **污染 D18 验收第 3 条要读的那份日志**。`restart.log` 是老板要求「失败要写清原因」的那份文件，现在里面会混进几十行「写结果失败」，运维读日志会被误导。
2. **失败就意味着结果没落盘**。`GET /api/update/restart/status` 读的就是 `restart_result.json`——真实重启时 helper、探活实例、正式实例三方几乎同时收尾，正撞在这个窗口上，D18 第 4 条会偶发读到旧结果或不完整结果。
3. 断言名已经点出了方向：「**固定临时名会让后写的把先写的 `.tmp` 删掉**」。但另一条静态断言「临时名唯一（mkstemp）」又是 PASS 的 —— 说明**模板里的 mkstemp 确实唯一，挂的另有其处**，大概率是 `os.replace` 在 Windows 上撞 `WinError 32`（目标文件正被别的进程打开）。

### 建议

- `write_result` 改成「唯一临时名 + `os.replace` 重试（指数退避，3~5 次）」；
- 失败时**不要**往 `restart.log` 写「写结果失败」这种噪音，改写到独立的 `restart_error.log`，主日志只留业务结论；
- 加一条断言：480 次并发写，`restart_result.json` 最终必须是**最后一次写入**的那个 tag（现在是「合法单对象」，但没验是不是最新的）。

---

## D24（P1）· 阶段6「覆盖 6/6 阶段」与老板决策冲突 → 每轮必红

失败原文：

> `[阶段6] 阶段覆盖完整（漏测要计数，不能只写进报告头）`
> 期望：本次自测覆盖全部 6 个阶段
> 实际：只跑了 5/6，漏测 ④ 竣工图清稿

但：**阶段 4（竣工图清稿）是老板 2026-10-31 明确决定不测的**（需 Windows + AutoCAD），`run_loop.cmd` 固定 `--phases 1,2,3,5,6`。

→ 这条断言**每一轮都必然红**，跟产品好坏无关。

### 危害

小问题？不是。这是「狼来了」的典型：每轮都有一条红，真实的回归信号就埋在噪声里，没人会再认真看红灯。上一轮（`20261110_210412`）阶段6 也是 `passed 0 / failed 1`，同一个原因。

### 建议

把「**按老板决定主动跳过**」和「**该跑没跑（漏测）**」区分开：

- 阶段4 由 launcher 显式列入 `skipped_by_decision`，断言判为 `skipped` 并计入 `summary.skipped`，**不判红**；
- 只有「launcher 说要跑、实际没跑」才算漏测判红。

---

## D25（P1）· 自测项目未删除，D19 复现（而且这轮连删都没试）

- 轮次结束后 `自测_20261111_073328`（`a6443da1`）仍在 `/api/projects` 里，`file_count=0`，磁盘目录完整（`.node_id` / `doc_relations.json` / `exports` / `generated_docs` / `index.json`）。
- `data/operation_log.jsonl` 里**没有任何 `delete` 或 `delete_failed` 记录** —— 说明本轮**根本没发起删除**，不是删了失败。
- 对照：2026-11-10 14:34 那轮曾一次性删掉 3 个自测项目；`c8c39eee` 那轮是 `delete_failed`（`WinError 32 data_level0.bin`）后由我手工删的。

→ 两种失败模式并存：**要么没删，要么删不掉**。请把清理放进 `finally`，无条件执行；并保证 `delete_failed` 一定留痕。

> **根因已在下一节定性**：删不掉是因为 chroma 句柄没释放；重启服务后同一个请求即成功。修法见下。

---

## D26（P3）· `POST /api/scan` 的 409 守卫存在竞态窗口

```python
# app/main.py:229
if SCAN_STATUS.get("running"):
    raise HTTPException(409, "已有扫描任务在运行")
# app/main.py:231
SCAN_STATUS.update({"running": False, "done": 0, "total": 0, ...})
# app/scanner.py:762（后台线程里才置真）
status["running"] = True
```

`running` 在 API 里被**先置 False**，过一会儿才由后台线程置 True。
→ 这个窗口里来的第二个 `POST /api/scan` 不会被 409 拦住，会起第二个扫描线程，两个线程共写同一个全局 `SCAN_STATUS`。

代码已经 `import threading` 了，加个 `threading.Lock` 或用 `Event` 做「启动中」状态即可。

---

### D19 根因已定性（本轮实测Confirmed，请按这个改）

报告写完后我做了一次对照实验，**把 D19 从「原因不明」变成「根因确定」**：

**实验 A（服务在跑，直接删）**

```
POST /api/projects/delete {"project_id":"a6443da1","backup":false,"delete_data":true}
→ {"ok":false,
   "error":"PermissionError: [WinError 32] 另一个程序正在使用此文件…:
            data\projects\a6443da1\vector_db\4e187094-…\data_level0.bin；
            残留 16 项：[…,'index.json','parsed_cache']",
   "partial_delete":true, "data_deleted":false}
```

**实验 B（重启服务释放句柄后，同一个请求原样再发一次）**

```
POST /api/update/restart   → 15668 → 6092，10 秒完成
POST /api/projects/delete  → {"ok":true,"message":"项目「自测_20261111_073328」已删除（含项目资料）",
                              "data_deleted":true,"log_written":true}
磁盘检查 → projects/a6443da1 目录已彻底不存在
```

**结论：删除逻辑本身没错，是 chroma 的 `PersistentClient` 打开后不释放 `data_level0.bin`，服务进程自己攥着句柄。**

→ 修法很明确：删除项目前，先把该项目对应的 chroma client 关掉/清出客户端缓存（`client.reset()` + `del`，或删前 `chroma_client_cache.pop(project_id)` 并 `gc.collect()`），再删目录。**不要靠重启服务来绕过** —— 那只是我这边的临时手段。

另外提醒：实验 A 那 16 项残留**不会自动清理**，`partial_delete=true` 后项目记录还在列表里，用户会以为没删成功又点一次，越点越乱。建议 `partial_delete` 时也把记录改成「待清理」态并给出重试入口。

## 顺带说清楚：阶段3 那 6 条不用改

`竣工资料统计 / 组卷清单 / 按车间组卷 / 整卷生成 / 一键竣工 / 缺件清单` 全部因为 `total_devices=0` 报错。原因是阶段1 没有数据入库（D23），**阶段3 无设备可查**。

这不是阶段3 的缺陷。D23 修好后这 6 条应自动转绿——**请以这个为标准验证 D23 是否真修好**：如果 D23 修了、阶段3 还有红的，那才是阶段3 自己的问题。

---

## 环境层我这轮动了什么（备案）

| 项 | 改动 | 原因 |
|---|---|---|
| 计划任务 `FangongAI-AutoFeedback` | `WakeToRun` False → **True** | 02:04、07:04 两轮被跳过（`MissedRuns=2`），夜里等于没跑 |
| `run_loop.cmd` | 去掉 `--no-restart` | D18 已验证修复；不撤则新版本永远不生效 |
| 手动触发一轮 | 07:33 | `last_tested_commit` 还停在 `d3cb449`，v0.1.233 从未被自动循环测过 |

---

## 附件

| 文件 | 说明 |
|---|---|
| `logs/selftest_report.json` | 71 条断言原始记录，11 条 `passed=false` |
| `logs/suites.json` | 专项套件汇总 P23/F1/T24 |
| `logs/console.log` | 自测控制台原文 |
| `logs/test_restart_really.out.txt` | 重启套件单独复现全文，含「LOG 记失败 38 次」 |
| `logs/_loop.log.tail.txt` | 本轮循环日志尾部 |
| `logs/report_self.json` | `reports/20261111_073324/report.json` 副本 |
