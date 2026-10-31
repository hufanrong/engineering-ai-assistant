# 通道缺陷工单 · PULL 段吃掉刚建的空报告目录（阻塞无人值守）

- 提交方：WORKbuddy（本机实测侧）
- 目标版本：`79b4c39` / workbench v0.1.179
- 严重级别：**P0（通道自身）**——不修则无法无人值守；每遇到远端有新提交就可能「拉完就死」，比不跑更糟
- 本轮不是自测轮：最近一轮自测结果见 `reports/20261031_072322/`（v0.1.179，52 通过 / 1 失败，已推送 `79b4c39`）

---

## 一、现象

2026-10-31 07:17 手动触发一轮常驻循环（`wb_loop.py --once`）：

```
[07:17:24] ===== 本轮开始 20261031_071724，本地 a1a7b1fdb21c =====
[07:17:42] 远端有 3 个新提交，拉取
07:22:15 进程退出 rc=1
```

实际结果：

| 应有 | 实际 |
|---|---|
| `reports/20261031_071724/` 报告目录 | **不存在** |
| `report.json` / `report.md` / `env.json` | **都没有** |
| commit + push 回传 | **没有**（`git log` 无该轮提交） |
| `.wb_loop_state.json` 记账 | **未更新**（仍停在 `1ed529f`） |
| 自测是否跑了 | **跑了**——`workbench/tools/selftest_report.json` 时间戳 07:21:57，内容有效 |

即「测试做了、报告没了、回传丢了」，与本脚本自己写的原则「失败不装成功、每步留证据」直接冲突。

## 二、对照实验

| 轮次 | 参数 | 结果 |
|---|---|---|
| 20261031_071724 | 默认（带 PULL） | rc=1，**无报告、无回传**，自测已跑完 |
| 20261031_072322 | `--no-pull` | rc=0 收尾，报告齐全（6 个文件）并成功回传 `79b4c39`，52 通过 / 1 失败 |

差异只有一个变量：**PULL 段**。

## 三、受控复现（最小步骤，7 秒）

```bash
cd D:\fangong-loop
mkdir reports/__probe_empty
python -c "import sys;sys.path.insert(0,'workbench/tools');import wb_loop as w,os;\
print('before',os.path.isdir('reports/__probe_empty'));\
ok,steps=w.pull_latest();\
print('ok',ok);[print(s['step'],s['rc']) for s in steps];\
print('after',os.path.isdir('reports/__probe_empty'))"
```

实测输出：

```
probe exists before: True
pull ok = True
   git stash（保住本地改动） rc= 0  Saved working directory and index state On main: wb_loop auto-stash ...
   git fetch                      rc= 0
   快进到 origin/main             rc= 0  Already up to date.
   git stash pop                  rc= 0  On branch main ...
probe exists after : False          ← 空目录被吃掉，pop 不会恢复
```

## 四、根因

`one_round()` 第 1 步就建好了本轮报告目录：

```python
out_dir = os.path.join(REPORTS_DIR, run_id)
os.makedirs(out_dir, exist_ok=True)     # 此时是空目录
```

之后 PULL 段（`pull_latest()`）见到工作树有未跟踪文件（`.wb_loop_state.json`、上一轮未提交的 report.json 等），执行：

```python
git("stash", "push", "-u", "-m", "wb_loop auto-stash ...")
```

`-u` 会清理未跟踪内容；**git 不跟踪空目录，所以清掉后 `stash pop` 不会把空目录恢复回来**（只恢复文件）。于是：

1. `out_dir` 消失；
2. 后续 `run_selftest()` 往 `out_dir` 拷 `selftest_report.json`、`run_selftest()` 的落盘、`env.json` 写入全部失败或静默跳过；
3. `finish()` 无法写 `report.json`，`commit_and_push` 无可提交内容 → 整轮**无任何回传**；
4. 进程以 `--once` 的退出码约定返回 1，外层只能看到「退出了」，看不到原因。

**触发条件（很常见）**：远端有新提交 **且** 工作树存在未跟踪文件 **且** 本轮报告目录尚为空。无人值守高频运行下几乎必然踩到——因为每轮都会先建空目录，而工作树经常带着上一轮未提交的 state 文件。

## 五、修法建议

**方案 A（推荐，最小改动）**：把 `out_dir` 的创建挪到 PULL 之后，或在 PULL 结束后无条件重建：

```python
# one_round() 中 pull 段之后
out_dir = os.path.join(REPORTS_DIR, run_id)
os.makedirs(out_dir, exist_ok=True)   # 防止被 stash 清掉
```

**方案 B（防御性，建议与 A 同时做）**：stash 时排除 `reports/`，只保代码现场：

```python
git("stash", "push", "-u", "-m", msg, "--", ".", ":!reports")
```
（注意：paths pec 排除写法需实测，`:(exclude)reports` 语法在部分 git 版本行为不同，建议以 A 为主、B 为辅。）

**方案 C（可观测性，必须一起修）**：`finish()` 写盘处包一层显式错误捕获，写盘失败时至少把错误打到 stderr 并落一个最小 `report.json`，不要静默丢轮。

## 六、附带两个会让排查变难的小问题

1. **`log()` 没有 flush**：`--once` 一轮被重定向到文件时，stdout 全缓冲，进程异常退出会丢掉全部日志——本次只剩两行，就是丢缓冲的结果。建议 `print(..., flush=True)` 或 `sys.stdout.reconfigure(line_buffering=True)`。
2. **`--once` 退出码语义**：`return 0 if one_round(a) in ("passed",) else 1`，即「跑完但有用例失败」也返回 1，与「通道崩了」同码。外层脚本无法区分「测试有失败（正常）」和「通道崩了（异常）」。建议 failed → 0（本轮已成功产出报告），error → 2。

## 七、验收标准

1. 在「远端有新提交 + 工作树有未跟踪文件」条件下跑 `--once`：`reports/<run_id>/` 必须存在且含 `report.json`、`env.json`、`console.log`，并有对应 commit + push；
2. 第 3 节的受控复现：`probe exists after` 必须为 `True`，或该探针目录被明确记为可删除；
3. 写盘失败时 `report.json` 里能看到原因，不允许「进程退出但无任何报告」。


## 八、复现环境的注意事项（会影响判断，必须说明）

第一次受控探针（07:34 左右）完整跑完，输出 `probe exists after: False`，即空目录确实被 `stash -u` 清掉、`stash pop` 没恢复。

第二次复跑同一探针（07:36）时，进程在 **`git stash push -u` 这一步被本机沙箱的删除保护拦截并终止**，输出停在 `probe exists before: True`，没有 traceback、退出码 1。也就是说：

- 「空目录被 stash 吃掉」这个机制在 git 语义上成立（第一次探针已证明）；
- 但这台机器上还有第二重干扰：**批量删除未跟踪文件会触发 WORKbuddy 沙箱的 safe-delete 保护，把进程直接杀掉**。这与第 1 轮「静默 rc=1、无 traceback」的症状一致，无法完全排除它也是诱因之一。

因此建议 AI 侧：
1. 在**不带沙箱的普通 cmd 窗口**里，用第 3 节脚本再复现一次，确认单纯 git 语义下的表现；
2. 修法优先选**方案 A（拉取后重建 out_dir）**——它不依赖 stash 行为，两种诱因都能兜住；
3. 如果确认 `stash -u` 在本机会被拦，长期应改成「不 stash 报告目录」（方案 B），避免每轮都触发一次批量删除。

---

修好之后，本机再装 Windows 计划任务做无人值守（这一步等这条修复合入后再做）。
