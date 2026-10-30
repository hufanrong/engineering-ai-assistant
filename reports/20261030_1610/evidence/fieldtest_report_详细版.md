# 繁工AI v0.1.174 本地实测报告（Windows 11 + 真实资料）

- 实测时间：2026-10-30 14:39 ~ 16:10（GMT+2）
- 安装目录：`D:\fangong-workbench-v0174\fangong-workbench`（解压 377 个文件 / 11,931,131 字节，PACKAGE_MANIFEST version=0.1.174）
- 运行环境：Windows 11 26200 / Python 3.13.14（venv）/ 端口 8756
- 原始日志：`raw\install2.log`、`raw\fieldtest2.log`、`raw\fieldtest.log`、`raw\tpl_scan.json`

---

## 零、结论先行

| 项 | 结论 |
|---|---|
| v0.1.174 本轮要确认的修复（`{{占位符}}` → `【待补充】`） | **成立**。120 份内置模板、5452 个占位符、空数据渲染后 `{{` / `}}` 残留 **0**，`【待补充】` 落盘 5452 处；真实 Word（COM）打开 4 份成品核对，残留均为 0 |
| 安装包能不能装 | **原样装不上**，两处硬阻断：`install.bat` 换行符为纯 LF（cmd 不识别）；`pip install -r requirements.txt` 在 Python 3.13 上解析到 numpy 1.26.4 源码包，无编译器构建失败 |
| 能不能走完业务链路 | **不能**。卡在三处：登记表无「册」列导致一键整卷恒 0 产出；一键竣工服务端 500；扫描队列无界增长把事件循环占满，整站无响应 |
| 建议发版前处理 | 见第五节优先级 P0/P1 |

---

## 一、装包与验装

### 1.1 原样装包失败的两处证据

**（1）`install.bat` 无法执行**——文件为 UTF-8 无 BOM + 纯 LF（0 个 CRLF），cmd 按行解析时错位：

```
'��?' 不是内部或外部命令，也不是可运行的程序
'p' 不是内部或外部命令 ...
'以启动：双击' 不是内部或外部命令 ...
```

同批文件对比（`install_optional.bat`、`open_or_start.bat` 是 CRLF+BOM，可正常执行）：

| 文件 | 字节 | CRLF | BOM |
|---|---|---|---|
| install.bat | 1111 | **0** | 无 |
| install-full.bat | 1267 | **0** | 无 |
| run_workbench.bat | 383 | **0** | 无 |
| run_loop.bat | 1216 | **0** | 无 |
| install_optional.bat | 1750 | 52 | 有 |
| open_or_start.bat | 1691 | 52 | 有 |

> 影响面：手册第一节、第三节让用户执行的正是 `install.bat` 与 `run_workbench.bat`，两个都是坏的。

**（2）依赖装不上**——`pip install -r requirements.txt` 在 Python 3.13 下：

```
Collecting chroma-hnswlib==0.7.6 (from chromadb==0.5.5)
  Downloading chroma_hnswlib-0.7.6.tar.gz
Collecting numpy (from sentence-transformers==3.0.1)
  Downloading numpy-1.26.4.tar.gz (15.8 MB)
  Preparing metadata (pyproject.toml): ... error
  meson ... Running `cl`/`gcc`/`clang` gave [WinError 2]
error: metadata-generation-failed  (numpy)
```

根因：`chromadb==0.5.5` 拉入 `chroma-hnswlib==0.7.6`，pip 回溯把 numpy 降到 1.26.4（该版本无 cp313 轮子）→ 触发源码构建 → 本机无 C 编译器 → 失败。`requirements.txt` 注释里已写明「Python 3.13 需 chromadb>=1.5.9」，但 `install.bat` 只做 `pip install -r requirements.txt`，注释不生效。

### 1.2 本轮采用的变通（已记录，便于复核）

1. 将 4 个 .bat 转为 CRLF+BOM（原件留存 `_orig_bat\`）；
2. 核心依赖按 requirements 锁定版本单独安装（全部成功）；
3. 向量栈按 requirements 自带注释改版本：`chromadb 1.5.9` + `sentence-transformers 6.2.0` + `torch 2.15.0`（全部成功，`retrieval=vector` 实测生效）。

### 1.3 自检结果

| 模式 | 通过 | 失败 | 跳过 | 备注 |
|---|---|---|---|---|
| 离线 `verify_install.py` | 7 | 0 | 2 | 可选依赖缺 paddleocr；端口空闲 |
| 在线 `--base http://127.0.0.1:8756` | 8 | **1** | 2 | 首页判定误报，见下 |

版本号三处一致：`config=0.1.174 api=0.1.174`；内置模板 121 个 + `_table_index.json`；中文与空格路径写入通过。

**首页 FAIL 是自检脚本的阈值问题，不是页面问题**：

```
[FAIL] 首页可打开: 200 bytes=193830 | 体积仅 193830 字节，可能是错误页
```

包内 `web/index.html` 实际大小就是 193830 字节，接口返回 193830 字节 = 完整页面。`verify_install.py` 里写死 `len(raw) > 200_000`，与本版前端体量冲突，**任何正常安装都会亮 FAIL**。

---

## 二、真实业务实测（用老板自己的资料）

### 2.1 用的什么资料

| 材料 | 实际路径 | 规模 |
|---|---|---|
| 设备台账 | `D:\Data\Downloads\选矿厂设备台账20251028（表1清单样式）.xlsx` | 182,481 B，11 个 sheet，主表 195 行设备 / 16 个车间 |
| 整编要求登记表 | `资料整编要求(1).xlsx`（本机仅在 WPS 备份区存有 `.et` 快照，已还原为 xlsx） | 25,521 B，Sheet1 共 **233 条**、24 个类别文本块 |
| 资料目录 | `D:\Users\hufanrong\Desktop\安装资料\选厂\重介质` | 237 个文件（该目录全量 9,050 个文件，取样重介质子目录以控制时长） |

### 2.2 每一步的实际数字

| 步骤 | 结果 | 数字 |
|---|---|---|
| 建项目 | PASS | id=3ec3d15f，名 `实测_20261030_152124` |
| 台账上传解析（首次） | **FAIL 超时** | 180s 客户端超时；服务端首次触发 embedding 模型 `paraphrase-multilingual-MiniLM-L12-v2` 下载 |
| 台账上传解析（模型已缓存） | PASS | 22.84s，status=parsed，parser=excel，entities=87 |
| 台账设备识别 | PASS | `device_count=186`（台账 195 行） |
| 设备→车间映射 | **0** | `device_workshop=0`，台账「车间」列没被用起来 |
| 资料扫描 | PASS | found=159 / parsed=159 / vectorized=79 / failed=0 / duplicate=0，入库 160 |
| 自动归车间 | 基本失效 | 4 组（未归车间/选矿厂/重介质车间/马诺诺重介质车间），**未归 154 / 160（96%）**；且出现「熟料送存仓」「锂辉石库」等按文件内容误判的车间名 |
| 资料库检索 | PASS | 5 条，`retrieval=vector` |
| 按车间预填 | PASS（但空） | `devices=0` |
| 生成 Word（HTTP 客户端视角） | **FAIL 超时** | 180s 超时；服务端实际已落盘 `generated_docs\施工方案\繁工AI_施工方案_20261030_153053.docx`（document.xml 4123 B，`{{` 残留 0） |
| 导入整编登记表 | PASS | total=233，`books={'（未标册）':233}` |
| 一键整卷（第一册） | **FAIL** | 生成 0 / 待办 0 / 归集 0 / 错 0 / 空壳 0，耗时 **135s**；报错「整编要求登记表中没有「第一册」这一册的条目」 |
| 一键整卷（换成「（未标册）」） | **FAIL** | 同样 0 产出，耗时 135s；响应里 `available_books: []` |
| 一键竣工归档 | **FAIL 500** | 服务端 `TypeError: string indices must be integers, not 'str'` @ `app/completion_archive.py:246`（`req["type"]`，req 实为 str）；客户端随后 `AttributeError` @ `tools/fieldtest.py:681` 崩溃，本轮报告未被写出 |
| 服务健康 | **FAIL 卡死** | 8756 端口 LISTEN，但 `GET /` 与 `/api/status` 均 30s 无响应；`upload_queue` 文件数 96 → 160 → **357** 持续增长，日志中 embedding `Batches` 行 279 行，事件循环被占满 |

### 2.3 登记表卡死整卷的根因（最影响交付的一条）

`app/supervision_integration.py:89` 按 `it['册']` 过滤条目：

```python
b = _clean_book(book)
return [it for it in load_registry() if _clean_book(it.get('册')) == b]
```

老板这份登记表是「类别 / 序号 / 资料名称 / 对应规范表号」四列（A 列为类别、B 列序号），**没有「册」列**。解析后 233 条全部记为「（未标册）」，且条目里没有 `册` 键 → `_book_items()` 对任何册名都返回空 → `available_books: []` → 一键整卷永远报「没有这一册」。

界面此时没有任何提示「登记表缺册列，请补列」，用户只会认为软件坏了。

---

## 三、v0.1.174 修复的实测证据（本轮核心）

### 3.1 全量模板空数据渲染

对象：`templates_builtin` 下全部 120 份 docx；调用 `supervision_templates._fill_element(root, {})`（空数据 = 所有字段都未填）。

| 指标 | 数值 |
|---|---|
| 模板数 | 120（全部成功，0 出错） |
| 占位符总数 | **5452** |
| 其中被 Word 拆成多个 run 的 | **0**（内置模板均为程序生成，占位符落在单个 `w:t` 内） |
| 渲染后 `{{` 残留 | **0** |
| 渲染后 `}}` 残留 | **0** |
| `【待补充】` 落盘 | **5452** |

补充：代码对跨 run 场景是**结构上覆盖**的——`_fill_para_text()` 先把整段所有 `w:t` 文本拼起来再匹配替换，写回第一个 `w:t` 并清空其余，这正好是「`{{` / `施工单位` / `}}` 被切成三段」的正确解法。本包内置模板恰好没有这种形状，所以该项实测计数为 0，属于模板生成方式所致，不是缺陷。

### 3.2 真实 Word（COM）打开核对

| 成品 | `{{` 残留 | `【待补充】` | 表格数 |
|---|---|---|---|
| 监理模板_设备开箱检查记录.docx | 0 | 72 | 9 |
| 监理模板_CTPT交接试验记录.docx | 0 | 26 | 1 |
| 监理模板_设备安装检查记录.docx | 0 | 45 | 9 |
| 监理模板_隐蔽工程验收记录.docx | 0 | 7 | 1 |

成品样本见 `成品样本\*.docx`，可直接双击用 Word 复核。

### 3.3 部分字段已填时的行为

以 `设备开箱检查记录` 传入 `施工单位=紫金建设`、`设备名称=离心泵`、`规格型号=P-101`：

- 三个字段各替换 9 处，正确；
- 其余 5 个字段（供货厂家/分部工程/单位工程/施工图号/项目经理）落成 `【待补充】`，共 45 处；
- 残留 `{{` = 0。

**判定：v0.1.174 的修复在 Windows + Word 真机环境下成立。**

---

## 四、哪里用起来别扭（代码测不出来的部分）

1. **装完就打不开界面**——两个 .bat 坏掉，用户第一次双击只会看到一屏乱码，第一印象直接崩。这是最该修的一条。
2. **第一次导台账像卡死**——首次解析要静默下载 470MB 模型，界面没有任何「正在下载模型」提示，180 秒后用户只会强杀进程。
3. **整卷永远 0 产出且不说原因**——登记表没有「册」列，这件事在导入时完全看不出来（界面显示 total=233，看着很正常），点了整卷才报「没有第一册」，且换「（未标册）」也不行。建议导入时就校验并明确提示「缺『册』列，已全部归入未标册，请先补列或按未标册整卷」。
4. **自动归车间几乎不工作**——把 237 个明确放在「重介质」目录下的资料扫进去，仍有 154/160 未归车间，反而凭空识别出「熟料送存仓」「锂辉石库」。目录名这么强的信号没用上，只能靠正文瞎猜。
5. **台账里的「车间」列被忽略**——195 行设备、车间列写得明明白白，`device_workshop=0`，导致后面按车间预填 `devices=0`、整卷按车间取设备也取不到。
6. **点一次扫描，整站瘫掉**——扫描队列文件数一路涨到 357，`/api/status` 和首页都 30 秒不响应。工地电脑常有别的窗口开着，用户会以为死机。
7. **长任务没有进度**——台账解析 22s、整卷 135s、生成 Word >180s，前端/接口都没有进度反馈，实测脚本自己也因此连续超时。

---

## 五、优先级建议

| 级别 | 问题 | 建议动作 |
|---|---|---|
| P0 | 4 个 .bat 是 LF 换行 | 打包时统一 CRLF + BOM；打包脚本加校验 |
| P0 | requirements 在 Python 3.13 不可解 | 按 Python 版本分流（3.12- / 3.13+ 两套 pin），或把向量栈降为可选安装 |
| P0 | 登记表无「册」列 → 整卷恒 0 | 导入即校验并提示；`_book_items` 对无册条目回落到「（未标册）」 |
| P0 | 一键竣工 500（`req["type"]` 收到 str） | `app/completion_archive.py:246` 入参类型校验 |
| P1 | 扫描队列无界增长、事件循环卡死 | 队列去重 + 限流；扫描转后台线程，保证 `/api/status` 不被饿死 |
| P1 | 台账「车间」列未用于设备归属 | 解析台账时写入 device→workshop 映射 |
| P1 | 归车间只认正文、不认目录名 | 目录名优先，正文兜底 |
| P1 | 首页自检阈值 200000 与 index.html 193830 冲突 | 阈值下探到 150000，或改判「包含关键模块 + 200 且非错误页」 |
| P2 | 首次 embedding 模型下载无提示 | 启动时预检模型，或首次给出明确等待提示 |
| P2 | `tools/fieldtest.py:681` 对 str 调 `.get()` | 加类型兜底，避免整轮报告不产出 |

---

## 六、回传清单

| 文件 | 说明 |
|---|---|
| `verify_install.json` | 自检原始报告（在线模式，含首页 FAIL 证据） |
| `fieldtest_report.json` | 本轮实测结构化数据（fieldtest.py 崩溃未自动写出，此份由 WORKbuddy 依日志整理，数字均可回溯） |
| `fieldtest_report.md` | 本文件 |
| `raw\install2.log` | 依赖安装失败的原始输出 |
| `raw\fieldtest2.log` | 完整业务实测原始输出（含 500 堆栈） |
| `raw\tpl_scan.json` | 120 份模板的占位符统计明细 |
| `成品样本\*.docx` | 4 份 Word 可打开的成品，用于人工核对 `【待补充】` |
