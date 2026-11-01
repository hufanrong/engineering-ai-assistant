# 缺陷工单 20261101_095058 · 完整性检查恒为 0 的两个根因

- 状态：**failed**（2 条待修，见下）
- 代码版本：`2cd0761b9a3c`（workbench v0.1.185，sync 于 `364e2e9`）
- 类型：诊断工单（`kind=defect-ticket`），不是一轮自测
- 起点：20261101_073651 那轮唯一的红项 `阶段3 完整性检查 → 200 phases=6 有资料的阶段=0`

## 一、结论

这条红项不是一个原因，是**两个独立根因叠在一起**。修掉任一条都不够，两条都要改。

| 编号 | 定性 | 位置 | 一句话 |
|---|---|---|---|
| **C1** | 产品缺陷 P1 | `app/completeness_check.py:98` | 上传资料索引读的是全局 `data/index.json`，那个文件根本不存在；索引实际在 `data/projects/<id>/index.json` |
| **C2** | 自测脚本缺陷 P2 | `tools/selftest.py:506` → `:581` | 阶段1 结束把项目切回「原项目」，阶段2 才生成资料 → 资料落进**上一轮的项目**；阶段3 又切到**本轮项目**去查 → 恒为 0 |

C2 是这条红项的直接成因；C1 是藏在后面的真问题 —— 就算 C2 修好、红项变绿，C1 照样让完整性检查看不见用户上传的任何资料。**C1 比 C2 严重得多**，只是它没有断言盯着，一直没暴露。

## 二、C1：完整性检查永远认不出「上传的资料」

### 代码

```python
# app/completeness_check.py:96-112
def _load_index_docs() -> set:
    """从上传文件索引中检测已有的资料类文件（按文件名关键词匹配）。"""
    idx_path = os.path.join(config.DATA_DIR, "index.json")   # ← 全局路径
    if not os.path.exists(idx_path):
        return set()
```

```python
# app/completeness_check.py:154-160
generated = _load_generated_docs()      # v0.1.168 已改成项目级：archive._gen_dir()
uploaded  = _load_index_docs()          # ← 仍是全局，漏改
existing_types = set(generated.keys()) | uploaded
```

`_load_generated_docs()` 在 v0.1.168 已经改成跟项目走（`archive._gen_dir()` 落到 `<项目目录>/generated_docs`），同一文件里的 `_load_index_docs()` **没有同步改**。

### 实测

```
$ ls data/index.json
（不存在，命令无输出）

$ ls data/projects/686a5bec/
exports  index.json  parsed_cache  project_meta.json  relations.json  uploads  vector_db  volumes

$ 19 个自测项目的索引位置统计
0494be15  自测_20261031_104430  docx类型=1 docx=1  index条=11
60268ea6  自测_20261101_013801  docx类型=1 docx=1  index条=11
686a5bec  自测_20261101_073742  docx类型=0 docx=0  index条=11
（全部 19 个项目都有 index.json，没有一个是全局的）
```

### 后果

`_load_index_docs()` 在任何项目下都返回空集，于是 `existing_types` 只剩「用 docgen 生成过的类型」。用户把整套到货验收记录、隐蔽验收记录扫成 PDF 传进去，`/api/completeness/check` 依旧报「缺失」。**这是把「已上传」全判成「缺」，方向性错误，不是漏报。**

影响面：`check_completeness()` 是 `/api/completeness/check` 的唯一实现，`/api/completeness/todo`（待补充清单）与 `/api/completeness/phase-status` 若复用同一份判定也一并受影响 —— 需 AI 侧确认后两个接口的取数路径。

### 建议改法

按 v0.1.168 的口径把索引也项目化，直接复用现成的项目级访问器（`app/project_paths.py:98`，带一次性历史迁移）：

```python
# app/completeness_check.py:96-98
from . import project_paths as _pp     # 文件顶部
...
def _load_index_docs() -> set:
    idx_path = _pp.data_file_with_legacy("index.json")   # 项目级 + 历史文件自动迁移
    if not os.path.exists(idx_path):
        return set()
```

更彻底的做法是别靠文件名关键词去猜类型，改问 `doc_relations`（阶段3 车间级资料已经在用 `_dr.workshop_has_doc_type`），全局一套判定，别两套口径。

### 同一处还有 3 个兄弟，建议一起过一遍（待 AI 侧确认影响面）

同样是「读全局 `config.DATA_DIR/index.json`」的写法还出现在：

| 位置 | 说明 |
|---|---|
| `app/docplan.py:91` | 文档计划 |
| `app/main.py:1391` | 主程序内的一处索引读取 |
| `app/equipment_merge.py:504` | 用的是传进来的 `data_dir`，需看调用方传的是哪个目录 |

`app/main.py:1694` 已经改成 `_pp.data_file("index.json")`（项目级，正确写法）。**这 3 处是否已造成其它功能退化，我没有做黑盒验证**，只报代码位置，不做结论 —— 请 AI 侧自查，别当已确认缺陷。

## 三、C2：资料生成在上一轮的项目里，检查在本轮的项目里

### 时序（tools/selftest.py）

| 行 | 动作 |
|---|---|
| `:419` | 阶段1 新建本轮自测项目，`TEST_PROJECT_ID` = 本轮 id |
| `:504-506` | 阶段1 结束：`call("POST","/api/projects/switch",{"project_id": origin["id"]})` —— **切回原项目**（也就是上一轮的自测项目） |
| `:510` | 阶段2 开始生成资料 —— 此时停在**原项目** |
| `:581-582` | 阶段3 开头：`switch` 到 `TEST_PROJECT_ID` —— 切回**本轮项目** |
| `:603-607` | 阶段3 断言 `有资料的阶段` —— 在本轮项目里查，而本轮项目根本没生成过资料 |

```python
# tools/selftest.py:603-607
code, body, err = call("GET", "/api/completeness/check")
phases = (body or {}).get("phases") or []
filled = [ph for ph in phases if ph.get("existing")]
record(P, "完整性检查", "200 且至少一个阶段有已存在的资料",
       f"{code} phases={len(phases)} 有资料的阶段={len(filled)}", code == 200 and bool(filled), err)
```

`:578-580` 那条注释（v0.1.173 加的）说的是「phase1 结束时切回了用户原项目，而竣工/整卷的数据都在自测项目里，所以阶段3 要切过去」。方向是对的，但只补了阶段3 一头，**没管阶段2 的资料被生成到哪去了**。

### 实测（本轮 07:36 那轮，文件时间 07:41）

```
$ find data -name "*.docx" -newermt "2026-11-01 07:30"
./projects/60268ea6/generated_docs/施工方案/繁工AI_施工方案_20261101_074117.docx
./projects/60268ea6/exports/监理模板_仪表回路试验记录_1号车间_20261101_074122.docx
./projects/686a5bec/volumes/第一册/1号车间/1_设备开箱检查记录.docx
./projects/686a5bec/volumes/第一册/1号车间/2_设备安装检查记录.docx
./projects/686a5bec/volumes/第一册/1号车间/_卷内目录.docx  …
```

- `60268ea6` = **上一轮**（20261101_013801）自测项目，本轮生成的施工方案、监理模板全落在这里；
- `686a5bec` = **本轮**（20261101_073742）自测项目，只有一个**空的** `generated_docs/`：

```
$ ls -laR data/projects/686a5bec/generated_docs        （本轮项目）
686a5bec/generated_docs:
total 4
drwxr-xr-x  … 0 Nov  1 07:41 .
drwxr-xr-x  … 0 Nov  1 07:41 ..

$ ls -laR data/projects/60268ea6/generated_docs        （上一轮项目）
60268ea6/generated_docs:
drwxr-xr-x  … 0 Nov  1 07:41 施工方案          ← 父目录 mtime 是 01:41，子目录 07:41 才生出来
60268ea6/generated_docs/施工方案:
-rw-r--r--  … 37670 Nov  1 07:41 繁工AI_施工方案_20261101_074117.docx
```

两个项目的 `generated_docs` 目录 mtime 都是 **07:41** —— 同一分钟内，一处只建了空目录（本轮项目，阶段3 切过去后 `_gen_dir()` 顺手建的），另一处落了实际文件（上一轮项目，阶段2 生成时还停在那里）。这是 C2 最直接的物证。

- 而 `施工方案` 正好是 `PHASES[0]["project_docs"]` 的第一项。也就是说：**只要在同一个项目里查，这一项必然 ≥1，红项立刻变绿** —— 断言没错，是上下文错位。

### 顺带一个副作用

每轮都会往「上一轮项目」里塞一份施工方案 + 一份监理模板，19 个自测项目的 `generated_docs` 越积越多。这会让「项目隔离」类用例拿到脏数据（上一轮的残留被当成这一轮的成果），属于假绿灯风险。

### 建议改法

推荐 A：阶段2 开头切回本轮项目，让「生成」和「检查」在同一项目里。

```python
# tools/selftest.py phase2 开头
if TEST_PROJECT_ID:
    call("POST", "/api/projects/switch", {"project_id": TEST_PROJECT_ID})
```

B 方案（阶段1 不切回、阶段5 再切回）也行，但改动面更大，会牵动阶段2 的其它用例。

**不建议**把阶段3 的 switch 去掉 —— 那样读到的是上一轮项目残留，红项会变绿，但是假的。

## 四、跨版本核对：这条红项不是新版本引入的

| 轮次 | 版本 | 完整性检查结果 |
|---|---|---|
| 20261031_143653 | 早期 | 200 phases=6 有资料的阶段=0 |
| 20261031_160653 | 早期 | 200 phases=6 有资料的阶段=0 |
| 20261101_013708 | e35e6b9 sync | 200 phases=6 有资料的阶段=0 |
| 20261101_073651 | v0.1.185 | 200 phases=6 有资料的阶段=0 |

跨 4 轮、跨多个版本数值完全一致 —— 与「上下文错位」的解释吻合（结构性问题，不随版本波动）。

## 五、复测判据（下一轮自动跑怎么算过）

1. `阶段3 完整性检查` → `有资料的阶段 ≥ 1`，且 `phases=6`；
2. **新增用例**：上传一份文件名含 `docgen.TYPES` 中类型的资料（如「设备开箱检查记录.pdf」），再调 `/api/completeness/check`，断言 `existing` 里出现该类型 —— 这条专盯 C1，没有它就永远测不出「上传资料被无视」；
3. `阶段3` 其余 13 项保持通过，`阶段1/2/5` 保持全绿（当前 15/9/9 全过）。

## 六、本轮不是自测轮，别误读

`report.json` 里 `summary` 记 `failed=2`，指的是**两条待修缺陷**，不是「自测 2 项失败」。本轮没有跑自测（`console.log` 里是诊断命令，不是 selftest 输出）。自测的最近一次真实结果仍是 `20261101_073651`：P46 / F1 / S0。
