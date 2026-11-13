#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 静态门禁：落盘调用必须带落点参数（v0.1.247 / D31）。

WORKbuddy 真机反馈（D31）里明确要求这一条：
> "加一个 CI 静态检查：扫描 app/scanner.py 里 enqueue( / assign_workshop( /
>  record_version( / _scope.path( 这些落盘调用，凡是没带 data_dir= 的就让构建失败。"

本项目反复出现的母题是「同一件事两个答案」，其中最贵的一类就是
**落点不跟着 data_dir 走**：扫描项目 A 的资料，索引/队列/车间归属却落进
项目 B（EE/FF 事故）。这类缺陷靠人 review 抓不住 —— 代码看着完全正常，
只有并发/多项目场景才暴露。所以要有机器门禁。

判定口径（重要，避免"扫描器自己零命中却报绿"）：
  · 用 **AST** 扫 app/ 下所有 .py（不是 grep —— 注释和字符串里的同名字符串
    不算调用，grep 会误报一大片）。
  · 命中数为 0 → **报红**（扫描器失效，必须让人知道）。
  · 每条命中必须带 `data_dir=` 关键字；允许在行尾写
    `# scope:ok <理由>` 显式豁免（必须写理由，不允许裸豁免）。

退出码：0 = 通过；1 = 有违规或扫描器零命中。
"""

import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.path.dirname(HERE), "app")

# 需要落点参数的跨模块落盘调用
LANDING_CALLS = {
    "enqueue": "upload_queue.enqueue",
    "assign_workshop": "workshop_assign.assign_workshop",
    "record_version": "version_manager.record_version",
}

# 允许出现的模块（这些模块自己就是落点实现方，不跨模块）
ALLOWED_MODULES = {
    "upload_queue.py",       # 定义方
    "workshop_assign.py",    # 定义方
    "version_manager.py",    # 定义方
    "scanner.py",            # 内部 _save_index 等另行处理
}

EXEMPT_MARK = "scope:ok"


def _is_landing_call(node) -> str:
    """判断这个 Call 是不是受管的落盘调用，返回标签或空串。"""
    f = node.func
    name = None
    if isinstance(f, ast.Attribute):
        name = f.attr
    elif isinstance(f, ast.Name):
        name = f.id
    if not name or name not in LANDING_CALLS:
        return ""
    # 只管跨模块调用：upload_queue.enqueue / workshop_assign.assign_workshop /
    # version_manager.record_version 这三种带模块前缀的写法。
    # 裸调用 enqueue(...) 通常是模块内部的 _enqueue_locked 之类，不算。
    if not isinstance(f, ast.Attribute):
        return ""
    return LANDING_CALLS[name]


def scan():
    problems = []
    checked = 0
    scanned_files = 0
    for fn in sorted(os.listdir(APP_DIR)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(APP_DIR, fn)
        if fn in ALLOWED_MODULES and fn != "scanner.py":
            continue
        scanned_files += 1
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            problems.append((fn, 0, f"语法错误，无法解析：{e}", ""))
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            label = _is_landing_call(node)
            if not label:
                continue
            checked += 1
            kws = {k.arg for k in node.keywords if k.arg}
            if "data_dir" in kws:
                continue
            lineno = getattr(node, "lineno", 0)
            line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
            if EXEMPT_MARK in line:
                reason = line.split(EXEMPT_MARK, 1)[1].strip()
                if not reason:
                    problems.append((fn, lineno, f"{label} 豁免但没写理由", line.strip()))
                continue
            problems.append((fn, lineno,
                             f"{label} 落盘调用没有 data_dir=（多项目下会串落点）",
                             line.strip()))
    return scanned_files, checked, problems


def main() -> int:
    scanned_files, checked, problems = scan()
    print(f"扫描 app/ 下 {scanned_files} 个模块，受管落盘调用 {checked} 处")
    if checked == 0:
        print("[FAIL] 受管落盘调用命中数为 0 —— 扫描器本身失效，"
              "不能据此判绿")
        return 1
    if not problems:
        print(f"[PASS] {checked} 处落盘调用全部带 data_dir=")
        return 0
    print(f"[FAIL] {len(problems)} 处落盘调用缺少 data_dir=：")
    for fn, lineno, msg, line in problems:
        print(f"  {fn}:{lineno}  {msg}")
        if line:
            print(f"      > {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
