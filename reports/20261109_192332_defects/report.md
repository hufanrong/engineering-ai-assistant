# WORKbuddy 缺陷清单回传 20261109_192332_defects

- 性质：**缺陷清单**，不是一次自测轮次（不触发 selftest）
- 代码版本：`5010f2b7fb38`
- 生成时间：2026-11-09 19:23:32
- 汇总：已修 16 项 / 待上游决策 5 项 / 合计 21 项

## 一、这次全部失败的项

按老板要求，失败项不隐瞒，逐条列出：

| 阶段 | 失败项 | 实测现象 | 根因 |
|---|---|---|---|
| 阶段② | 单据生成之后的 5 项 | 阶段只跑了 4 项就中断，汇总显示 3 通过 1 失败 | 打印 docx 二进制内容到 GBK 控制台抛 UnicodeEncodeError |
| 阶段⑥ | 设备数自身一致 | `list=0 stats=None`，断言 `len(devices)==stats.devices` 失败 | 真实项目 relations.json 无 stats 键，接口未兜底 |
| 整轮 | 20261109_071408 那轮 | 整轮作废，报告目录为空 | 报告目录先建后被 `git stash -u` 删除 |
| 启动 | 双击 run_loop.bat | 直接退出，提示找不到 Python | 只认 PATH，真实用户 PATH 无 python/git |

## 二、问题清单

| 编号 | 类别 | 问题 | 级别 | 状态 |
|---|---|---|---|---|
| CH-01 | 通道 | run_loop.bat 只认 PATH 上的 python/git，真实用户 PATH 两者皆无，双击必挂 | blocker | 已修 |
| CH-02 | 通道 | git push 返回 rc=128 且 stderr 全空 | blocker | 已修 |
| CH-03 | 通道 | .bat 含中文 + chcp 65001 时 cmd 按字节错位，rem 行被劈开当命令执行 | blocker | 已修 |
| CH-04 | 通道 | .bat 带 UTF-8 BOM 导致首行 @echo off 失效、echo off 未生效 | major | 已修 |
| CH-05 | 通道 | 报告目录先建、后被 git stash -u 删除，写 console.log 时 FileNotFoundError 整轮崩 | blocker | 已修 |
| CH-06 | 通道 | finish() 推送后二次写盘不再提交，远端 report.json 永远缺 pushed、commit_after 自指 | major | 已修 |
| CH-07 | 通道 | selftest_report.json/md 已被 .gitignore 声明忽略却仍被跟踪，每轮必脏 | minor | 已修 |
| CH-08 | 通道 | workbench/updates/ 未忽略，每轮进 stash | minor | 已修 |
| ST-01 | 自测 | 阶段② 打印 docx 二进制内容触发 UnicodeEncodeError，阶段从 9 项截断到 4 项 | blocker | 已修 |
| ST-02 | 自测 | 阶段⑥「设备数自身一致」必挂：真实项目 relations.json 无 stats 键，接口返回 stats=None | major | 已修 |
| ST-03 | 自测 | worktree 下 .git 是 55 字节指针文件，isdir 判断导致「不是 git 仓库」 | major | 已修 |
| ST-04 | 自测 | report.json/md 在 commit 之后才写，--once 单轮永远回传不到结论 | major | 已修 |
| OP-01 | 待决策 | 每轮现在会产生两次提交（报告提交 + post-push 补提交），提交数量翻倍 | minor | 待决策 |
| OP-02 | 待决策 | run_loop.bat 硬编码了随程序附带的运行时路径作为兜底探测，属机器相关 | minor | 待决策 |
| OP-03 | 待决策 | 阶段⑥ 两项跨接口校验在「无空间模型/无设备」时直接跳过，真实项目上等于没测到 | major | 待决策 |
| OP-04 | 待决策 | 历史 4 轮报告不完整：20261030_1610 / 20261031_073500 / 20261031_103857 / 20261101_095058 | info | 待决策 |
| OP-05 | 待决策 | 仓库外仍存在临时启动器 D:\fangong-launcher\run_loop_local.bat，与仓库脚本重复 | info | 待决策 |
| ME-01 | 我方失误 | 11-06 用 cmd //c 验证 PATH，继承了 Bash 注入的环境，误报「python/git 正常，不是机器缺陷」 | major | 已修 |
| ME-02 | 我方失误 | 统计未推送文件时报 123 个，实为 134 个 | minor | 已修 |
| ME-03 | 我方失误 | 改启动器时引入回归：for /d 带引号 + 正斜杠解析错，找不到 python | major | 已修 |
| ME-04 | 我方失误 | 用 LF 写 .bat 导致每行首字符丢失（'ouble-click'） | minor | 已修 |

## 三、已修的根因（都在代码本体，不靠外部脚本）

1. **run_loop.bat 自给自足**：绝对路径探测 git（含 `PortableGit\versions\*` 与随程序附带的运行时）并把 `mingw64\bin;bin;usr\bin` 前置——`usr\bin\sh.exe` 是 `!`-前缀凭据助手的前提，缺它 push 会 rc=128 且 stderr 全空；python 依次探测 `.venv`、`venv`、PATH、用户目录、Program Files、附带运行时，并用 `import fastapi` 实测。正文改纯 ASCII，因为 cmd 在 `chcp 65001` 后读含中文的 .bat 会按字节错位（见 `evidence/01-*.txt`）。
2. **阶段② 不再被编码掐断**：`selftest.record()` 打印前捕获编码异常降级，不再依赖外部先设 `PYTHONIOENCODING`。
3. **阶段⑥ stats 恒为 dict**：`load_relations()` 读时按真实条数重算 `devices/workshops`，让这个不变量由结构保证。
4. **远端终于有 pushed**：新增 `commit_followup()`，推送后二次写盘的内容会补提交补推送（此前 26 轮远端报告无一含 pushed）。
5. **报告目录不再被 stash 吃掉**：stash 加 `:(exclude)reports`，并在 PULL 后补建一次目录。
6. **临时产物不再污染工作区**：`selftest_report.json/md` 移出版本索引，`workbench/updates/` 加入 .gitignore。

## 四、待上游决策

- **OP-01**（minor）：每轮现在会产生两次提交（报告提交 + post-push 补提交），提交数量翻倍。建议：建议 commit 前就把 pushed 预留为 True、commit_after 用占位，推送后只更新 state
- **OP-02**（minor）：run_loop.bat 硬编码了随程序附带的运行时路径作为兜底探测，属机器相关。建议：建议抽成 install.bat 写出的 .runtime.json 或环境变量 WB_PYTHON，脚本只读配置
- **OP-03**（major）：阶段⑥ 两项跨接口校验在「无空间模型/无设备」时直接跳过，真实项目上等于没测到。建议：建议自测造一个最小关系图谱样本，把这两项从跳过变成真跑
- **OP-04**（info）：历史 4 轮报告不完整：20261030_1610 / 20261031_073500 / 20261031_103857 / 20261101_095058。建议：原始产物已不存在，无法补全；建议今后缺件时由 wb_loop 在 report.json 里显式记 missing[]
- **OP-05**（info）：仓库外仍存在临时启动器 D:\fangong-launcher\run_loop_local.bat，与仓库脚本重复。建议：仓库脚本修好后应删除它，避免两套逻辑分叉

## 五、我自己的失误（如实披露）

- **ME-01**：11-06 用 cmd //c 验证 PATH，继承了 Bash 注入的环境，误报「python/git 正常，不是机器缺陷」。已更正：真实用户 PATH 中既没有 python 也没有 git
- **ME-02**：统计未推送文件时报 123 个，实为 134 个。原因是未加 -z，八进制转义的中文路径被 grep 拆行；已用 -z 重算并更正
- **ME-03**：改启动器时引入回归：for /d 带引号 + 正斜杠解析错，找不到 python。已改用 for /f + dir /b /ad，并在精简 PATH 下复测通过
- **ME-04**：用 LF 写 .bat 导致每行首字符丢失（'ouble-click'）。所有 .bat 统一按 CRLF 写并校验 bareLF=0

## 六、历史完整性缺口（无法补全）

远端 26 轮中，18 轮 7 个文件齐全；4 轮仅缺 `telemetry_bundle.json`（该特性当时未上线）；4 轮有真缺口：

| 轮次 | 状态 | 文件数 | 缺什么 |
|---|---|---|---|
| 20261030_1610 | failed P14/F12 | 15 | 无 selftest_*、无 telemetry，且目录名本身残缺，混入手工产物 |
| 20261031_073500 | error | 4 | 缺 env.json + 全部 selftest 产物 |
| 20261031_103857 | error | 4 | 无 summary、无 selftest 产物，console.log 仅 116 字节 |
| 20261101_095058 | failed P0/F2 | 4 | 无 selftest 产物 |

原始产物已不存在，无法追溯补全。

## 七、验证明细

见 `evidence/` 目录（全部为真实抓取或真实重跑输出，非人工编写）：

- `evidence/01-bat-codepage-desync.txt`
- `evidence/02-gbk-print-crash.txt`
- `evidence/03-phase2-truncated.json`
- `evidence/04-report-json-missing-pushed.txt`
- `evidence/05-stash-deleted-report-dir.txt`
- `evidence/06-launcher-python-regression.txt`
