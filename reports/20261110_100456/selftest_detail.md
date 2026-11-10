# 繁工AI 四阶段自测报告

- 时间：2026-11-10 10:10:06
- 目标：http://127.0.0.1:8756
- 平台：Windows 11 / Python 3.13.14
- 样本目录：D:\fangong-workbench\workbench\data\uploads

## 汇总

| 阶段 | 通过 | 失败 | 跳过 |
|---|---|---|---|
| ④ 竣工图清稿 | 3 | 3 | 0 |

## 明细

### 阶段4 · 清稿环境自检 —— 通过

- 预期：ready=true
- 实际：200 ready=True missing=[] platform=Windows
- 证据：[]

### 阶段4 · 待清稿图纸清单 —— 通过

- 预期：200
- 实际：200 count=25

### 阶段4 · 清稿执行 —— **失败**

- 预期：200 且 status 非失败、失败条数为 0
- 实际：-1 status=(空) failed=None None
- 证据：TimeoutError: timed out

### 阶段4 · 原图 MD5 不变 —— 通过

- 预期：True
- 实际：c76077df05e6 -> c76077df05e6
- 证据：设计目标质量底线：原文件 MD5 全程不变

### 阶段4 · 处理日志 —— **失败**

- 预期：有逐图日志文件或日志条目
- 实际：log_file=(空) exists=False; 顶层条目=0

### 阶段4 · 成果 PDF —— **失败**

- 预期：生成合并 PDF（文件存在且非空）
- 实际： (0B)
- 证据：pdf=(空) exists=False size=0B pages=None
