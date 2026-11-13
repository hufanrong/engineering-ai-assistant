#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web/index.html 内联 JS 语法门禁（v0.1.248 新增）。

为什么需要它：
  整个前端是**一个** 4445+ 行的单文件 index.html，里面是**一整块**内联
  <script>。JS 语法一旦出错（少个分号、多个括号），浏览器会在解析阶段
  抛 SyntaxError 并**放弃执行整块脚本** —— 结果不是「某个按钮坏了」，
  而是**整个页面的所有 JS 函数都不存在**（切模块、上传、备份全废），
  而后端接口全都在、看起来「服务正常」。
  这是本项目吃过大亏的「哑巴故障」家族：出事了但一声不吭。

判据：
  · 抽出所有 <script>（不含 src= 的外链）→ 逐块写临时文件 → node --check；
  · **脚本块数为 0 即报红**（扫描器自身坏掉时不能给绿灯 —— 上一轮
    check_scope_calls 就踩过「零命中当通过」）；
  · node 不存在时**必须报红**，不许静默跳过（那等于没检查）。

跑法：python tools/check_web_js.py
退出码：0 = 通过；非 0 = 有语法错或工具缺失。
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.dirname(HERE)

TARGETS = [
    os.path.join(WB, "web", "index.html"),
]


def extract_scripts(path):
    """抽出 HTML 里所有**内联** <script> 块的正文。"""
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    blocks = []
    # <script ...> ... </script>；带 src= 的是外链，取不到正文，跳过
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", txt, re.S | re.I):
        attrs, body = m.group(1), m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        blocks.append(body)
    return blocks


def main():
    node = None
    for cand in ("node", "nodejs"):
        try:
            r = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                node = cand
                break
        except Exception:  # noqa: BLE001
            continue
    if not node:
        print("[FAIL] 找不到 node —— 无法校验前端 JS 语法（跳过检查 = 没检查）")
        return 2

    total_blocks = 0
    failed = 0
    tmpdir = tempfile.mkdtemp(prefix="fgwebjs_")
    for path in TARGETS:
        if not os.path.isfile(path):
            print(f"[FAIL] 文件不存在：{path}")
            failed += 1
            continue
        try:
            blocks = extract_scripts(path)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] 读取失败：{path} {type(e).__name__}: {e}")
            failed += 1
            continue
        if not blocks:
            # 零命中 = 扫描器坏了，不等于「页面没有 JS」
            print(f"[FAIL] {os.path.basename(path)} 没抽到任何内联 script —— 扫描逻辑坏了")
            failed += 1
            continue
        for i, body in enumerate(blocks):
            total_blocks += 1
            if not body.strip():
                continue
            js_path = os.path.join(tmpdir, f"block_{i}.js")
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(body)
            r = subprocess.run([node, "--check", js_path],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                failed += 1
                print(f"[FAIL] {os.path.basename(path)} 第 {i + 1} 块 script 语法错误：")
                print((r.stderr or r.stdout or "").strip()[:1500])
            else:
                print(f"[OK]   {os.path.basename(path)} 第 {i + 1} 块 script 语法通过 "
                      f"({len(body)} 字符)")

    if total_blocks == 0:
        print("[FAIL] 一块 script 都没校验到 —— 门禁自身失效")
        return 2
    print("-" * 60)
    print(f"校验脚本块 {total_blocks} 个，失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
