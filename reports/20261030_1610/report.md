# v0.1.174 实测回传 · 20261030_1610

- 状态：**failed**（14 通过 / 12 失败）
- 性质：手册第四节的**真实资料实测**，不是 wb_loop 自测（wb_loop 会拉代码+重启，与手工实测冲突，本轮未启用）
- 安装：`D:\fangong-workbench-v0174\fangong-workbench`，Python 3.13.14 venv，端口 8756
- 报告来源：`fieldtest.py` 在「竣工归档」崩溃未写出报告，本 `report.json` 由 WORKbuddy 依原始日志整理，`evidence/` 下为未改写的原始输出

## 一句话结论

**v0.1.174 要确认的修复成立**（`{{占位符}}` → `【待补充】`，Word 真机残留 0）；**但安装包原样装不上，业务链路三处卡死**（登记表缺「册」列导致整卷恒 0、一键竣工 500、扫描队列把事件循环占满）。

## 修复验证（核心）

| 项 | 数字 |
|---|---|
| 内置模板全量空数据渲染 | 120 份 / 5452 个占位符；`{{` 残留 **0**、`}}` 残留 **0**、`【待补充】` **5452** |
| Word（COM）真机打开 | 4 份 docx 残留均为 0；标记 72 / 26 / 45 / 7；表格 9 / 1 / 9 / 1 |
| 部分字段已填 | 3 字段各替换 9 处；其余 5 字段转标记 45 处；残留 0 |
| 跨 run 拆分 | 内置模板计数 **0**（程序生成，占位符在单 `w:t` 内）；代码按「拼接-替换-回写首 run」处理，结构上覆盖该形状 |

## P0（按影响排序）

1. **4 个 .bat 是 UTF-8 无 BOM + 纯 LF**（`install.bat`/`run_workbench.bat`/`run_loop.bat`/`install-full.bat`，CRLF=0）→ cmd 乱行，venv 建不出来。同级 `install_optional.bat`/`open_or_start.bat` 是 CRLF+BOM，可正常跑，说明是打包漏转换。
2. **`pip install -r requirements.txt` 在 Python 3.13 不可解**：`chromadb==0.5.5` → `chroma-hnswlib==0.7.6` → numpy 回溯到 1.26.4（无 cp313 轮子）→ 源码构建 → `metadata-generation-failed`。requirements 注释已写明 3.13 需 `chromadb>=1.5.9`，但 install.bat 只做 `pip install -r`，注释不生效。
3. **登记表无「册」列 → 一键整卷恒 0**：233 条全落 `（未标册）`，`available_books: []`；`app/supervision_integration.py:89` 按 `it['册']` 过滤，条目无此键，任何册名都匹配不上；换「（未标册）」同样报「没有这一册」，还白跑 135 秒。
4. **一键竣工 500**：`app/completion_archive.py:246` `req["type"]` 收到 str → `TypeError: string indices must be integers`；随后 `tools/fieldtest.py:681` 对 str 调 `.get()` 崩溃，导致整轮报告不产出。

## P1

- **扫描队列无界增长**：`upload_queue` 96 → 160 → **357**，embedding 日志 279 行；最终 8756 端口 LISTEN 但 `GET /` 与 `/api/status` 均 30 秒无响应（整站卡死）。
- **台账「车间」列未用于设备归属**：195 行设备、车间列齐全，`device_workshop=0` → 按车间预填 `devices=0`、整卷取不到设备。
- **自动归车间几乎不工作**：237 个明确放在「重介质」目录的资料，扫完未归 **154/160（96%）**，反而误识别「熟料送存仓」「锂辉石库」——目录名信号没用上。
- **`verify_install.py` 首页阈值误判**：写死 `> 200_000`，而 `web/index.html` 实际 193,830 字节，返回长度完全一致 → 任何正常安装都亮 FAIL。
- **首次导台账静默下载 470MB 模型**：首次解析 180s 超时，缓存后同一文件 22.84s；期间无任何提示。

## 输入材料

| 材料 | 规模 |
|---|---|
| 设备台账 `选矿厂设备台账20251028（表1清单样式）.xlsx` | 182,481 B，11 sheet，195 设备行 / 16 车间 |
| 整编要求登记表 `资料整编要求(1).xlsx`（本机仅存 WPS `.et` 快照，已还原） | 25,521 B，233 条，四列无「册」列 |
| 资料目录 `…\安装资料\选厂\重介质` | 237 文件（该目录全量 9,050 个，取样控时长） |

## 目录

```
report.json          机器可读（status/summary/by_phase/steps，ai_side.py 可直接读）
report.md            本文件
env.json             运行环境与依赖实装版本
console.log          三段原始输出原样拼接
evidence/
  install.log                     pip 失败堆栈
  fieldtest_main.log              业务实测主跑（含 500 堆栈与崩溃点）
  fieldtest_round1_timeout.log    第 1 轮（台账 180s 超时，对比用）
  verify_install.json             自检原始报告（在线模式）
  tpl_scan.json                   120 份模板占位符明细
  fieldtest_report_详细版.md/.json  完整版实测报告（含优先级建议）
  word_samples/*.docx             4 份 Word 可打开成品，供人工核对【待补充】
```
