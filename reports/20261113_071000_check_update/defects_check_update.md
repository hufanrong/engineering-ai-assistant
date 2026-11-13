# v0.1.243–246 检查更新 · 缺陷与建议回传

> 回传时间：2026-11-13 07:12 ｜ 实测版本：**v0.1.246**（HEAD `45a80ff`，与远端一致）
> 实测环境：Windows 本机真实工程资料（马诺诺 / 65 个文件 / 10 类格式，含 DWG + 扫描件 OCR）
> 立场说明：本文件不只是报缺陷。**目的是把这个产品做成「换工程不用改代码」的多项目平台**，所以每条缺陷后面都写了「这条属于 L1 框架 / L3 项目配置中的哪一层」以及「怎么改、怎么验」。

---

## 0. 一句话结论

**v0.1.245/246 的方向是对的**——把模块级全局（`upload_queue.QUEUE_DIR` / `LOG_PATH`）删掉，改成按 `data_dir` 现算落点，这正是「同一套代码服务多个施工项目」必须做的那一刀。

**但这一刀只切了一半**：`reparse_file()` 这条链已经全部跟随 `data_dir`（v0.1.212/214 修的，做得很干净，注释里还留了事故记录，值得保留这种写法）；**`scan_folder()` 这条主链路漏了 3 处**，于是「在哪儿扫就写到哪儿」的隔离承诺在主链路上不成立 —— 这就是本轮新缺陷 **D31**。

同时暴露出两个容易被误判的问题：
- **D32：测试资产没跟着重构同步**。删掉 `QUEUE_DIR` 之后，3 个专项套件还在引用它，一个直接 `AttributeError` 崩、一个在 `[C5]` 段崩、还有一个把 `os.listdir(None)`（= 列当前工作目录）数出来的 `PACKAGE_MANIFEST.json` 当成「队列包只活下来 1 个」。**这三条是假红**，会让开发端去修不存在的 bug，也会把真缺陷淹在噪声里。
- **D33：扫描进度不可观测 + 索引落盘间歇过大（真 P0）**。65 个真实文件扫 356.8s，自测放弃时 `index=0 / vector=0 / done=0/63`。隔离探针实测：一轮约 20 分钟，单文件 3~95s，最长心跳空档 75.8s，**「慢」和「死」在外部观测上完全同形**；更糟的是索引每 50 个文件才落一次盘，中断时 12 份解析缓存都在、`index.json` 一条都没有。自测阶段1、阶段3 里 12 条红断言，全部是这一条的下游。

**所以本轮不该被读成「质量倒退到 F12」**。准确的说法是：**12 条红里有 11 条是 1 条真 P0 的下游，4 条套件红里有 3 条是测试自己过期了。真正要去改的是 D31 和 D33 两条。**

---

## 1. 本轮新增了什么（先说做对的）

| 版本 | 内容 | 我的核验 |
|---|---|---|
| v0.1.243 | 设备身份键边界 + 空间模型与台账同源 | `test_device_identity_242` 21/21 通过 |
| v0.1.244 | 项目卡片车间数与车间清单同源 | `test_workshop_count_244` 通过；项目列表 `workshop_count` 与车间清单口径一致 |
| v0.1.245 | 平台参数隔离收敛：删模块级 `QUEUE_DIR`/`LOG_PATH`，落点改为 `_queue_dir(ddir)` | 方向正确，但见 D31/D32 |
| v0.1.246 | 多项目通用性 | 见 D31 |

另外这些**仍然是绿的**，没有回归：`test_restart_really` 48/48（D18 四项验收稳定）、`test_delete_sweep` 15/15（D19）、`test_ledger_authority` 15/15、`test_device_identity` 14/14、`test_project_audit_log` 24/24、`test_phase_coverage` 28/28、`test_gb_fallback` 193/0。

---

## 2. D31 · 隔离失效：扫描主链路还有 3 处落点没跟随 `data_dir`（P0）

### 现象（可稳定复现）

```
> python tools/test_multi_project_245.py
[PASS] M9  隔离目录扫描成功  None
[FAIL] M9b 当前项目的索引/归属/队列/版本台账一个字节都没变  被改动=['assign', 'queue_idx', 'version']
[FAIL] M9c 当前项目的上传队列没有多出包  前=0 后=2
[FAIL] M9d 隔离目录里确实落了解析缓存/索引/队列包（说明扫描真跑了）
[PASS] M9e 向量库落点也跟随 ddir  iso/vector_db=True
失败 3 条
```

判读（这三条 PASS/FAIL 合起来把范围钉死了）：

- `M9e` 绿 + `M9d` 红 → **向量库跟随了 `data_dir`，索引/队列没跟随**；
- `M9b` 被改动的是 `assign / queue_idx / version`，**不含 `index`** → `index.json` 走的是正确路径；
- 结论：**恰好 3 个业务文件的落点解析绕过了 `data_dir`**，不是全盘失效。

### 根因（三个具体的漏传点）

`app/scanner.py::scan_folder()`（427–627 行）里这一段的三个调用都没带 `ddir`：

| 行 | 代码 | 应该 |
|---|---|---|
| 528 | `upload_queue.enqueue(res)` | `upload_queue.enqueue(res, data_dir=ddir)` |
| 536 | `workshop_assign.assign_workshop(res.sha256, res.file_name, ..., file_path=path)` | 末尾补 `data_dir=ddir` |
| 546 | `version_manager.record_version(res.file_name, res.sha256, ...)` | **没有 data_dir 形参，见下** |

对照 `app/scanner.py::reparse_file()`（630–691 行）——**同一个仓里已经有正确写法**，657 / 666 行都带了 `data_dir=ddir`，注释还写明了当年的事故（「不传时 enqueue 恒落当前项目队列，实测单测造的 4 个样本让真实项目 pending 变成 4」）。**照抄这一段就能修 2/3。**

第 3 处不是漏传，是**接口缺维度**：

```python
# app/version_manager.py:49
def record_version(file_name, sha256, ts="", ..., mtime="") -> dict:   # 没有 data_dir
# 落点：
def _version_file() -> str:
    return _scope.path(_VERSION_NAME)          # 只能解析「当前项目」
```

```python
# app/project_scope.py:63
def path(filename, project_id=None, legacy_fallback=True) -> str:
    ddir = project_dir(project_id)             # project_id 或 None(当前项目)，没有 data_dir
```

**所以就算 `scan_folder` 想传也传不进去**。这是本轮最该改的结构问题，见 §5。

### 现场影响（已经有了真实案例）

- `data/projects/<马诺诺>/workshop_assign.json` 在 **04:28:33** 被改、`version_map.json` 在 **04:29:03** 被改 —— 正好落在 `test_source_path_fields` 的运行窗口内。
- 对老板的直观后果：**在临时目录/测试里做一次解析，真实项目的「待人工确认车间」和「多版本冲突」会凭空多出记录**，而界面上没有任何提示。

### 修法（按这个顺序）

1. **先修两个已支持 `data_dir` 的**（528/536 行），照抄 `reparse_file` 的写法，一行一个参数。
2. **再补接口维度**：`project_scope.path(filename, data_dir=None, project_id=None)`；`version_manager.record_version(..., data_dir=None)` → `_version_file(data_dir)`。`data_dir` 优先级最高，`None` 时才回落到当前项目。
3. **加一道 CI 守卫**（这条最重要，否则下一轮重构还会漏）：在 `tools/` 放一个静态检查，扫 `app/scanner.py` 里所有 `enqueue(` / `assign_workshop(` / `record_version(` / `_scope.path(` 调用，**形参里没有 `data_dir=` 或 `ddir` 就让构建失败**。人眼漏一次就是今天这个结果，机器不会漏。
4. **验收口径**（建议直接写进 `test_multi_project_245` 的 M9 段，已有断言不用改）：M9b/M9c/M9d 三条同时绿。

### 这条属于哪一层

**L1 框架层。** 「显式作用域优先、全局只作兜底」对所有施工项目都成立，与具体工程无关。换到任何新项目，这条规则都不用改。

---

## 3. D32 · 破坏性重构没带测试资产一起走，产出 3 条假红（P1，但会误导排障）

v0.1.245 删掉了 `upload_queue.QUEUE_DIR` / `LOG_PATH`（`app/upload_queue.py` 18–22 行的注释写明了删除理由，理由是对的）。但三个套件还在直接引用：

| 套件 | 位置 | 表现 | 性质 |
|---|---|---|---|
| `tools/test_upload_queue.py` | 90 行 `qdir = uq.QUEUE_DIR` | `AttributeError: module 'app.upload_queue' has no attribute 'QUEUE_DIR'` → **一条断言都没跑就退出**，`rc=1` | 假红（测试崩了） |
| `tools/test_source_path_fields.py` | 178 行 `old_q, old_l = UQ.QUEUE_DIR, UQ.LOG_PATH` | 打印完 `[C5] 临时目录里重解析不得写进真实项目队列` 就崩，脚本尾部只剩这行标题 | 假红（测试崩了） |
| `tools/test_atomic_io.py` | 72 行 `uq.QUEUE_DIR = None`；218 行 `os.listdir(uq.QUEUE_DIR)` | **`os.listdir(None)` 在 CPython 里等于列当前工作目录**，于是它数到的是 `workbench/PACKAGE_MANIFEST.json` → `[FAIL] 队列包 20 个一个不少  实得 1 个` | 假红（断言在数错地方） |

已验证：

```
> python -c "import os; print([f for f in os.listdir(None) if f.endswith('.json')])"
['PACKAGE_MANIFEST.json']        ← 就是它，跟上传队列没有任何关系
```

也就是说 **v0.1.246 并没有丢 19 个队列包**，`test_atomic_io` 的 [C] 段其他 3 条（索引 20 条齐全、无残留 .tmp、0 错误）都是绿的，只有计数那行看错了目录。

### 修法

1. **测试统一走公共函数**，不许直接摸私有常量：`uq._queue_dir()` / `uq._load_idx()`（这两个在 v0.1.245 里已经是纯函数）。
2. **删全局这种事，留一版弃用期**。建议：保留 `QUEUE_DIR` 作为只在 `_ensure()` 里赋值的 **兼容别名**，并在 `__init__` 里 `warnings.warn(..., DeprecationWarning)`，下个大版本再删。理由：这类常量被测试/脚本/外部工具引用的概率很高，硬删的收益是「代码干净」，代价是「所有引用方一起哑掉」——今天就是代价兑现的样子。
3. **`os.listdir(None)` 这种隐式行为要挡掉**：所有 `os.listdir` / `open` 的路径参数做一次 `if p is None: raise` 的自检，或直接上 `ruff` 规则。它不报错、静默返回一个看起来「差不多」的结果，是最难查的一类。

### 这条属于哪一层

**L1 框架层（测试契约）。** 建议在仓里立一条规矩：**被测模块的公共接口变更，必须同一个提交里更新所有引用方**，CI 跑一遍全量套件才算过。

---

## 4. D33 · 扫描整体空转：65 个真实文件 → 索引 0 条（P0，本轮最严重的用户可见问题）

### 现象

自测 `20261113_040421` 阶段1：

```
[PASS] 递归扫描启动: 200 {'ok': True, 'folders': ['D:\\...\\data\\uploads']}
[FAIL] 扫描完成: {}                                                  耗时 356.8s
[FAIL] 扫描按时结束: 心跳停止 301s（阈值 300s），判定卡死；done=0/63
[FAIL] 资料库条目数: 条目 0
[PASS] 索引与解析缓存一致: 200 index=0 cache=0 待补=0 孤儿文件=65     ← 65 个文件全在盘上，一个没入库
[PASS] 向量库计数: vector_count=0
```

下游连带红：资料库检索 0 命中、检索模式 `None`、竣工资料 `total_devices=0`、组卷「无设备数据」、一键竣工 0 台、缺件清单空 —— **阶段1 的 6 条 + 阶段3 的 6 条，全是这一条的扇出**。

### 隔离复现（`tools/probe_scan_hang.py`，本轮新写）

为了不靠猜，把同一条链路拉到单独进程里跑：`FANGONG_DATA_DIR` 指向临时目录（**真实项目一个字节都不动**）、源目录只读、逐 tick 打时间戳。

```
[    0.3s] cb done=0/63  开始解析（共 63 个文件）          (距上次回调 0.0s)
[    0.3s] cb done=0/63  解析中 01e625bc262b_2#立磨HRM31.2L-00WX外形图.pdf
[    2.3s] …（2s）[ 4.3s] …（4s） … [ 14.6s] …（14s）      (每 2.0s 一跳，正常)
Loading weights: 100%|█████| 199/199                        ← embedding 模型加载
[   90.4s] cb done=1/63  parsed: 01e625bc262b_2#立磨…pdf    (距上次回调 75.8s)  ← 停摆 75.8s
[   97.5s] cb done=2/63  parsed: 02c35437c627_…平台.pdf     (距上次回调 3.1s)
[  120.7s] cb done=3/63  parsed: 0533876f646f_…流程图.dwg   (距上次回调 4.9s)
[  197.3s] cb done=10/63 parsed: 297c8c2b01c5_…磨盘装置.pdf  (距上次回调 0.6s)
[  240.1s] scan_folder 抛异常 SystemExit: 超预算退出 耗时 239.9s（此时 done=12/63）
[  240.2s] index.json 存在=False 条数=-
[  240.2s] 最长回调空档 TOP5: [(75.8s, parsed 立磨外形图), (16.8s, …), (12.7s, …), (4.9s, …), (3.1s, …)]
[  240.6s] 源目录前后一致=True（证明只读，没动真实资料）
```

四个数字定住了性质：

| 观测 | 值 | 含义 |
|---|---|---|
| 首个 PDF 耗时 | **约 90s** | 单文件确实慢，不是「没跑」 |
| 最长心跳空档 | **75.8s**（`Loading weights` 期间） | 心跳确实会停，且与「卡死」无法区分 |
| 240s 内完成 | **12 / 63** | 按此速率一轮约 **20 分钟** |
| 中断后 `index.json` | **不存在** | 12 份解析缓存都在，索引 0 条 —— 见下 D33b |

### 根因（比我上一轮猜的更明确）

心跳挂在**扫描线程自己的 `progress_cb`** 上，而 `scan_folder` 的主循环里除了「解析」还有同步步骤：`store.index_file(res)`（首次会加载 embedding 模型）、`enqueue`、`assign_workshop`、`record_version`。**只要其中一步是同步长耗时，主线程就出不来，`cb` 不被调用，心跳一起停。** 这次抓到的正是 `Loading weights` 那 75.8s。

再叠加一层设计问题：**进度粒度只有「每个文件完成」**。一个文件 90s，`done` 就 90s 不动一次；63 个文件跑 20 分钟，界面和自动测试都只能看到「done 很小/不动」—— **「慢」和「死」在外部观测上完全同形**。自测判红、用户报「卡死」，都是这个设计必然的产物，不是偶发。

### D33b · 索引 50 个才落一次盘，中断即全丢（顺手抓到的，同样该修）

`app/scanner.py`：448 行 `_n_since_save = 0`，604 行 `if _n_since_save >= 50:` 才 `_save_index`。而本轮探针只跑到 12 个文件就被打断，结果是：

```
projects/probe01/
  parsed_cache/            有 12 份（每个文件的解析结果都在）
  upload_queue/            有包
  workshop_assign.json     已写
  version_map.json         已写
  vector_db/               已写
  index.json               ← **不存在**
```

**最坏的组合**：解析结果、队列、归属、版本、向量全都落了盘，唯独「资料库索引」一条没有。用户看到的是「扫了 20 分钟，资料库还是空的」。真实现场一旦遇到（服务被杀、用户点取消、断电、某个文件抛异常），代价是整轮重扫。

修法：**落盘节奏改成按时间**（每 5~10s 或每 5 个文件，取先到者），而不是按 50 个计数；并且取消/异常路径也要 `finally` 落一次。（现在 `break` 能落到 616 行的收尾，但**异常路径不会**。）

### 已排除的方向

- 不是服务死掉：同期阶段2/3/5 的接口都是 200；
- 不是 `progress_cb` 没接：`on_tick` 确实接上了（486–495 行），tick 机制本身好用（探针里每 2.0s 一跳很稳）；
- 不是 `data_dir`（那是 D31，两回事）；
- **超时兜不住也不是「设太小」**：`_parse_with_ticks` 的超时判断与 tick 在同一个循环里，主线程被同步步骤占住时它一样跑不到 —— 「超时保护」和「心跳」共用了同一个可能被阻塞的执行体，保护形同虚设。

### 修法（四条，按优先级）

1. **心跳与进度分离成两个字段**（最关键，成本最低）
   - `heartbeat`：由**独立 daemon 线程**每 2s 无条件刷新 —— 表示「进程还活着」；
   - `last_progress` / `in_flight_file` / `in_flight_seconds`：只在真正有进展（文件完成、阶段切换）时更新 —— 表示「活儿在往前走」。
   - 判活看 `heartbeat`，判死看 `last_progress + in_flight_file + in_flight_seconds`。这样既不会「假活」（你们在 `_parse_with_ticks` 注释里担心的陷阱），也不会「假死」（本次实测的坑）。
2. **进度粒度细化到阶段**：`解析中 / 向量化中 / 归类中 / 入库中`，`done` 旁边再给「当前文件已耗时」。界面能显示「正在解析 3/63（本文件 47s）」，用户就不会以为死了。
3. **超时与解析必须解耦**：慢且不可控的步骤（向量化、模型加载、OCR、DWG 转换）不要和 tick 循环共用执行体。要么放子进程（`Popen.communicate(timeout=)`，可硬杀），要么单独线程 + 看门狗只报警不动心跳。
4. **索引落盘改成按时间 + 异常也落**（D33b）。

### 顺带一个体验问题（同源）

首次扫描要加载 embedding 模型（`Loading weights 199/199`，本次占 75.8s）。**建议服务启动时预热**（后台异步加载，不阻塞 API），而不是等用户第一次扫描才付这 75 秒。预热完成前 `/api/status` 带 `vector_ready: false`，前端显示「向量库初始化中」，用户就知道该等。

### 验收口径（硬门槛，建议直接做成回归）

| 指标 | 门槛 |
|---|---|
| 65 个真实样本文件扫描完成 | `index.json` 条目数 ≥ 63（允许 2 个真不支持） |
| 任意两次 `heartbeat` 间隔 | ≤ 5s（独立线程刷，与干活快慢无关） |
| 任意两次 `last_progress` 间隔 | ≤ 30s，且必须能读出「当前文件名 + 该文件已耗时」 |
| 单文件耗时 > 60s | 必须在日志里留一行「慢文件 文件名/耗时/阶段」 |
| 单文件卡死 | ≤ 120s 必须放弃并计入 `stats["timeouts"]`，继续下一个 |
| 全量扫描总时长 | ≤ 45 分钟（实测 30~40 分钟是当前上限，暂按 45 分钟卡；后续做增量扫描自然下降） |

### 这条属于哪一层

**L1 框架层。** 「长任务要有心跳、要能超时、慢的地方要留痕」与工程无关，是平台底座能力。

---

## 5. D34 · 服务会无痕消失，且日志事后无法复盘（P1）

### 事实

- 07:00 前发现服务已停：端口 8756 仍显示 `LISTENING` 但 **PID 6520 已不存在**，三次 `/api/status` 全部 `HTTP=000`；
- `updates/restart_result.json` 仍停在 **11-11 07:59** → **没有走过 `/api/update/restart`**，不是重启流程杀的；
- `reports/service.log` 最后写入 **04:29:01**，末段无 traceback、只有正常解析输出 → **不是自崩，是被杀**；
- 用计划任务 `FangongAI-StartWorkbench` 恢复，30 秒就绪 v0.1.246 / PID 24380，三次采样 `HTTP=200`（8ms / 33ms / 9ms）。

### 日志本身的两个硬伤（这才是要改的）

```
> grep -c "2026-11-13" reports/service.log
0
```
- **整个 2.4MB 日志里没有一个时间戳**，没人能说清哪个事件发生在几点。这次只能靠文件 mtime 反推（`version_map.json` 04:29:03 ↔ `service.log` 04:29:01）。
- **没有启动/退出埋点**：没有 "启动 pid=/版本=/数据目录="，也没有退出原因。于是「重启了几次、上次是正常退出还是被杀」全靠猜。

### 修法

1. **日志行强制前缀时间戳 + 级别 + pid**：`2026-11-13 04:29:01.123 INFO [pid 24380] ...`。这一条对现场排障的价值最高，成本最低。
2. **启动/退出各打一条结构化日志**：启动写 `version / pid / data_dir / 当前项目`；退出捕获 `atexit` + `signal` + 未捕获异常钩子，写清退出码与原因。
3. **父进程守护**：既然 `StartWorkbench` 计划任务能在 30 秒内拉起服务，建议把它从「验收用的一次性任务」转成**常驻守护**（每 5 分钟探测 `/api/status`，连不上就拉起，并写一条「检测到服务不可用 → 已重启」的日志）。这样「服务没了」不再需要人工发现。—— 这条需要老板点头，我不擅自改计划任务。

### 顺便记录一个环境差异（不是产品缺陷，但会让人误判）

`service.log` 里有 `[safe-delete][SAFE_DELETE_FAIL_CLOSED]` / `[SAFE_DELETE_BULK_CONFIRM_REQUIRED]` 这类记录 —— 这是 **WorkBuddy 会话注入的 `sitecustomize.py` 沙箱守卫**，只有「从 WorkBuddy 会话里起的进程」才带它，**计划任务起的进程不带**。同一条代码因此会有两种行为（尤其涉及删除项目、批量操作）。建议在 `service.log` 启动埋点里明确写一行 `sandbox_shim=on/off`，避免下次又把沙箱行为当成产品 bug 追半天。

---

## 6. 平台化建议：把「落点」收成唯一入口（L1 框架，最重要的一条）

D31 不是「漏了 3 个参数」这么小的事。它暴露的是**落点解析的维度不够**：现在只有「当前项目」这一个隐式维度，任何「在别处处理数据」的场景（测试、离线校验、多工作区、导入导出、批量重建）都必须靠人肉在每个调用点补 `data_dir=`。补漏是必然的，因为**约束不在类型系统里，只在人的记忆里**。

建议按这个方向收口（一次改完，以后不再漏）：

```python
# 目标形态：显式作用域
class Scope:
    data_dir: str
    index: str; assign: str; queue: str; version: str; vector: str
    @classmethod
    def current(cls) -> "Scope": ...          # 只在 UI/API 入口处调用一次
    @classmethod
    def at(cls, data_dir: str) -> "Scope": ...  # 测试 / 离线 / 隔离目录

# 所有业务模块只接受 Scope，不接受"隐式当前项目"
upload_queue.enqueue(res, scope)
workshop_assign.assign_workshop(..., scope=scope)
version_manager.record_version(..., scope=scope)
scanner.scan_folder(folder, scope=scope)
```

配套三条纪律：
1. **禁止模块级可变全局**（v0.1.245 已经开了这个头，继续做完）；
2. **禁止在业务函数内部读「当前项目」**，只在入口解析一次往下传；
3. **CI 静态检查**：`app/` 下出现不带 `scope`/`data_dir` 的落点调用就让构建失败。

为什么这条对**多个施工项目**都成立：换工程时唯一变的是 `Scope` 指向的目录；框架代码、解析规则、归集逻辑一个字节都不用改。这就是老板说的「框架自动复用、工程数据隔离」。

---

## 7. 还没动的两块（沿用上两轮口径，未变）

### D29 / D30 · 台账 3709 行仍未入库

- 现状：马诺诺 **62 文件 / 24 台设备 / 2 个车间**（`中矿堆 from_ledger=true`、`粗碎车间 from_ledger=false`）；
- `火法部分工艺设备表（0430).xlsx` = 10 sheet / 3709 行 / **表头均在第 6 行** / 每个 sheet 的「子项名称」就是车间名 —— 至今一行没进去，`ledger_skipped_rows=200` 全来自它，理由全是「台账空行」；
- **这是 D30（解析规则硬编码列名 + 「首行即表头」假设）的表象**，不是独立 bug。修 D29 必须先修 D30，否则换个工程还得再改一次代码；
- 验收口径不变，四条同时满足才算过：设备 ≥600 台、识别车间 ≥8 个、位号非空率 ≥90%、熟料粉磨装置单车间 ≥60 台；
- **追加一条**：验收必须包含**一份合成工程**（sheet 名/表头位置/列顺序全部不同的假数据）跑通，否则只是给马诺诺打了补丁，平台没建起来。

### D23 · 心跳形态回归，但套件是绿的

- 阶段1「扫描按时结束」判红（301s），而 `test_scan_heartbeat` 本轮 **29/29 全绿（耗时 496.7s）**；
- 说明套件覆盖的场景（造的小样本）碰不到「单个大 PDF/大 DWG 卡住」这种真实情况 —— **测试绿 ≠ 产品对**；
- 修法见 D33 验收口径，请把这个真实场景（65 个文件含 DWG + 扫描件 OCR）做成套件的一部分，而不是继续用小样本。

---

## 8. 需要老板点头的事（我没动）

1. **三个自测残留项目**：`自测_20261111_120419`、`自测_20261111_170448`、`自测_20261111_220503`，各 60 文件 / 24 设备。按老板「测试项目用完直接删」的口径可以删，但要您一句话。
2. **三个老项目**：`v01201实测项目B`、9 个 `v01201实测_*`、`v182_195236` —— 仍逐条等您点头。
3. **`FangongAI-StartWorkbench` 计划任务**：建议转常驻守护（见 D34 修法 3），要不要改由您定。
