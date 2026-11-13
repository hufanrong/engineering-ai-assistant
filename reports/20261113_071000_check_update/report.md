# v0.1.243–246 检查更新 · 人读版摘要

- **实测版本**：v0.1.246（HEAD `45a80ff`，与远端一致）
- **实测时间**：2026-11-13 07:00–07:20
- **实测环境**：Windows 本机 + 真实工程资料（马诺诺 / 65 个文件 / 含 DWG + 扫描件 OCR）
- **结论**：方向对，刀只切了一半。**真缺陷 2 条（D31 隔离失效、D33 扫描空转）+ 3 条假红（D32 测试过期）+ 1 条运维缺口（D34 服务无痕消失）**

---

## 一、先说好消息

v0.1.245/246 干的事就是想做「同一套代码服务多个施工项目」：**把 `upload_queue` 的模块级 `QUEUE_DIR` / `LOG_PATH` 删掉，落点改成按 `data_dir` 现算**。这个方向完全正确，而且 `reparse_file()` 里已经把正确写法立起来了（v0.1.212/214，还带着当年事故的注释）。

没有回归的（本轮全绿）：`test_restart_really` 48/48、`test_delete_sweep` 15/15、`test_ledger_authority` 15/15、`test_device_identity` 14/14 + `_242` 21/21、`test_project_audit_log` 24/24、`test_phase_coverage` 28/28、`test_gb_fallback` 193/0、`test_archive_concurrency` 13/13、`test_atomic_write` 29/29。

---

## 二、本轮自测成绩与「怎么读」

| 轮次 | 结果 | 说明 |
|---|---|---|
| 2026-11-12 23:04 | **P74 / F1 / S2** | 上一轮最好成绩 |
| 2026-11-13 04:04（本轮） | **P57 / F12 / S3** | 阶段1 = P8/F6、阶段3 = P7/F6/S1、阶段6 = P24/F0 |

**不要直接读成「质量倒退」。** 12 条红里，**11 条是同一个根因（扫描空转）的下游**：

```
扫描 356.8s 结束，但 index=0 / vector=0 / done=0/63
  ├─ 资料库条目数 0            ← 扫描没入库
  ├─ 车间自动分类：正式 []、候选 []   ← 没有文件可归类
  ├─ 资料库检索 0 命中 / 模式 None   ← 库里空的
  └─ 阶段3 六条（竣工统计/组卷/按车间组卷/整卷/一键竣工/缺件）全部 total_devices=0
```

阶段3 那 6 条**不是竣工模块坏了**，是「没设备数据」——它们是 D29（台账 3709 行没入库）+ D33（扫描空转）的联合下游。修好这两条，它们会一起转绿。

---

## 三、四条要改的（详情见 `defects_check_update.md`）

### D31 · 隔离失效（P0，可稳定复现）

`scan_folder()` 主链路还有 3 处落点没跟随 `data_dir`：

| app/scanner.py | 调用 | 状态 |
|---|---|---|
| 528 | `upload_queue.enqueue(res)` | 缺 `data_dir=ddir` |
| 536 | `workshop_assign.assign_workshop(...)` | 缺 `data_dir=ddir` |
| 546 | `version_manager.record_version(...)` | **函数签名里就没有 `data_dir`**，属于接口缺维度 |

实证：

```
> python tools/test_multi_project_245.py
[FAIL] M9b 被改动=['assign', 'queue_idx', 'version']
[FAIL] M9c 当前项目上传队列 前=0 后=2
[FAIL] M9d 隔离目录里没落 index/queue
[PASS] M9e 向量库落点跟随 ddir  ← 说明只漏了这 3 个，不是全盘失效
```

现场后果已经有了：马诺诺的 `workshop_assign.json` 在 **04:28:33**、`version_map.json` 在 **04:29:03** 被真实改动，正好在 `test_source_path_fields` 运行窗口内。用户侧表现是「莫名其妙多出待确认车间和版本冲突」。

### D32 · 测试过期产出 3 条假红（P1，会误导排障）

`QUEUE_DIR` 被删后，三个套件还在引用：

| 套件 | 表现 | 真相 |
|---|---|---|
| `test_upload_queue.py:90` | `AttributeError`，**一条断言都没跑** | 测试崩了 |
| `test_source_path_fields.py:178` | 打完 `[C5]` 标题就崩 | 测试崩了 |
| `test_atomic_io.py:218` | `[FAIL] 队列包 20 个一个不少 实得 1 个` | **`os.listdir(None)` = 列当前工作目录**，数到的是 `PACKAGE_MANIFEST.json` |

已验证：`os.listdir(None)` → `['PACKAGE_MANIFEST.json']`。**v0.1.246 没有丢包。**

### D33 · 扫描进度不可观测 + 超时保护形同虚设（P0，用户可见）

65 个真实文件 → 自测等到 356.8s 放弃，此时 `index=0`、`vector=0`、`done=0/63`，65 个文件全在盘上没入库。

隔离复现（`tools/probe_scan_hang.py`，临时 DATA_DIR、源目录只读、逐 tick 打时间戳）：

```
[   14.6s] …（14s）                       每 2.0s 一跳，正常
Loading weights: 100%|█████| 199/199       ← embedding 模型加载
[   90.4s] parsed: 01e625bc262b_…PDF      (距上次回调 75.8s)  ← 停摆 75.8s
[  240.1s] 超预算退出（此时 done=12/63）
[  240.2s] index.json 存在=False          ← 12 份解析缓存都在，索引 0 条
```

- 首个 PDF 约 **90s**、单文件 3~95s，一轮约 **20 分钟**；
- 心跳挂在扫描线程自己的 `progress_cb` 上，而 `index_file`（首次加载模型）/ OCR / DWG 转换都是同一线程的同步调用 → **一步慢，心跳一起停**；
- 超时判断与 tick 在同一个循环里，被占住时同样跑不到 → `PARSE_FILE_TIMEOUT_SEC=120s` 形同虚设；
- 进度粒度只有「每文件完成」，一个文件 90s 就 90s 不动 → **「慢」和「死」在外部观测上完全同形**；
- **D33b**：索引 `_n_since_save >= 50` 才落盘，中断/异常时 12 个文件的解析结果全在缓存里、索引一条没有 → 用户看到「扫了 20 分钟资料库还是空的」，代价是整轮重扫。

修法：`heartbeat`（独立线程刷，判进程活）+ `last_progress / in_flight_file / in_flight_seconds`（判活儿在走）拆成两组字段；进度细化到阶段；超时与解析解耦（子进程硬杀）；索引改按时间落盘且异常路径也落。另建议服务启动时后台预热 embedding 模型，别让用户第一次扫描才付这 75 秒。

### D34 · 服务无痕消失（P1）

- 端口 `LISTENING` 但 PID 6520 已不存在，三次 `/api/status` 全 `HTTP=000`；
- `restart_result.json` 仍停在 11-11 07:59 → 没走重启接口，不是重启杀的；
- `service.log` 末段无 traceback → **不是自崩，是被杀**；
- **日志 2.4MB 里一个时间戳都没有**（`grep -c "2026-11-13"` = **0**），也没有启动/退出埋点 → 事后只能靠 mtime 反推；
- 已用 `FangongAI-StartWorkbench` 恢复：30 秒就绪 v0.1.246 / PID 24380，三次采样 `HTTP=200`（8ms/33ms/9ms）。

---

## 四、给开发端的主线建议（这不是马诺诺专有的）

把「落点」收成一个显式作用域对象，业务函数只接受它、不再读「当前项目」：

```python
class Scope:
    data_dir; index; assign; queue; version; vector
    @classmethod
    def current(cls): ...      # 只在 API/UI 入口调用一次
    @classmethod
    def at(cls, data_dir): ...  # 测试 / 离线 / 隔离目录
```

配套：① 禁止模块级可变全局（v0.1.245 已开头，做完）；② 业务函数内部禁止解析「当前项目」；③ **CI 静态检查**：不带 `scope`/`data_dir` 的落点调用直接让构建失败。

理由：补漏靠人的记忆一定会再漏（D31 就是），只有落到类型和 CI 上才不漏。而这条对所有施工项目都成立 —— 换工程时唯一变的是 `Scope` 指向哪，框架代码一个字节不用改。

---

## 五、需要老板点头的事（我没动）

1. 三个自测残留项目（各 60 文件 / 24 设备）：`自测_20261111_120419`、`自测_20261111_170448`、`自测_20261111_220503`
2. 三个老项目：`v01201实测项目B`、9 个 `v01201实测_*`、`v182_195236`
3. `FangongAI-StartWorkbench` 是否转常驻守护（本轮第二次靠它恢复服务）

---

## 六、本轮产物

| 文件 | 内容 |
|---|---|
| `report.json` | 机器可读记录（AI 侧读取口径） |
| `report.md` | 本文件 |
| `defects_check_update.md` | 缺陷详情 + 根因 + 修法 + 验收口径（主交付） |
| `evidence_check_update.json` | 关键证据逐条落档 |
| `logs/selftest_0413_failures.txt` | 12 条失败 + 2 条跳过的原文（含预期/实际/证据） |
| `logs/multi_project_245.out.txt` | D31 复现全文 |
| `logs/atomic_io.out.txt` | D32 假红全文 |
| `logs/probe_scan_hang.txt` | D33 隔离复现（时间戳逐 tick） |
| `logs/loop_tail.txt` | 自动循环日志尾部 |
| `logs/task_stdout_tail.txt` | 计划任务原始 stdout/traceback（D28 修复后的通道） |
