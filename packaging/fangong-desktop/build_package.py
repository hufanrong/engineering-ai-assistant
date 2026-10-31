#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI 安装包构建器 · 从工作区生成可分发的 ZIP。

为什么不用 git archive：某几次修复是通过 GitHub Git Data API 直接推送的，
本地 git 索引可能落后于远端。用 git archive 打出来的包可能少了刚修的文件。
所以这里**直接按工作目录的当前内容打包**，打完再回读校验版本号与关键文件。

用法：
    python build_package.py --src <workbench源目录> --out <输出zip> [--tag v0173]

包含：app/ parsers/ web/ tools/ docs/ cloud_server/ templates_builtin/ platform_data/
      start.py *.bat requirements*.txt README.md .gitignore
      data/templates 下的模板库（内置模板首次启动会自动注册，但带上省一次冷启动）
排除：data/projects（各项目业务数据）、data/*.json、data/generated_docs、data/uploads、
      data/vectordb、data/backups、data/telemetry、data/upload_queue、cloud_server/cloud_data、
      venv/、__pycache__/、*.pyc、*.log
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile

# 必须打进包的顶层文件
TOP_FILES = [
    "start.py", "README.md", ".gitignore",
    "install.bat", "install-full.bat", "install_optional.bat",
    "open_or_start.bat", "run_workbench.bat", "run_loop.bat",
    "requirements.txt", "requirements-ocr.txt",
]

# 必须打进包的目录（整目录递归，过滤掉 __pycache__）
TOP_DIRS = [
    "app", "parsers", "web", "tools", "docs", "cloud_server", "templates_builtin",
]

# 完全排除（路径前缀，相对 workbench 根）
EXCLUDE_PREFIX = [
    "data/projects", "data/generated_docs", "data/uploads", "data/vectordb",
    "data/backups", "data/telemetry", "data/upload_queue", "data/exports",
    "cloud_server/cloud_data", "venv", ".venv", "__pycache__", "updates",
]

# data/ 下这些**要**带上（首次启动即可用，不带也能跑但会多等一次注册）
DATA_KEEP = [
    "data/templates",
]

EXCLUDE_SUFFIX = (".pyc", ".pyo", ".log", ".tmp")

# 运行期生成的自测报告：里面会写死测机器的绝对路径和当时的版本号，
# 打进安装包会泄露路径、也会让收件人看到与自己无关的版本数字。
EXCLUDE_REL_FILES = [
    "tools/fieldtest_report.json",
    "tools/fieldtest_report.md",
    "tools/selftest_report.json",
    "tools/selftest_report.md",
    "tools/verify_install.json",
    "tools/last_install_verify.json",
]


def should_skip(rel):
    rel = rel.replace("\\", "/")
    if rel.endswith(EXCLUDE_SUFFIX):
        return True
    if "__pycache__" in rel.split("/"):
        return True
    if rel in EXCLUDE_REL_FILES:
        return True
    for p in EXCLUDE_PREFIX:
        if rel == p or rel.startswith(p + "/"):
            return True
    return False


BOM = b"\xef\xbb\xbf"


def _bat_to_bom_crlf(path: str) -> bool:
    """把 .bat 规整成 **UTF-8 BOM + CRLF**（v0.1.177）。

    实测事故：用户双击 install.bat，cmd 报「'xxxxx' 不是内部或外部命令」、
    中文全是乱码。根因是随包的 .bat 存成了「UTF-8 无 BOM + 纯 LF」：
    ① 没有 BOM，cmd 按系统 ANSI 代码页解码，中文全成乱码，控制流语句被截断；
    ② 纯 LF，cmd 对多行 call/if 块的续行判定失效，脚本执行到一半就散架。
    同目录下本来正常的 install_optional.bat / open_or_start.bat 都是 BOM+CRLF，
    说明只是打包时漏转，内容本身没问题 —— 所以**在打包这一步强制归一化**，
    不论工作区里存成什么样，出厂一律合规；回读阶段再断言一次，防止回归。
    返回 True 表示原文件不合规、已被修正。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except Exception:
        return False
    body = raw
    if body.startswith(BOM):
        body = body[3:]
    body = body.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    fixed = BOM + body.replace(b"\n", b"\r\n")
    if fixed == raw:
        return False
    with open(path, "wb") as f:
        f.write(fixed)
    return True


def _bat_noncompliant(data: bytes) -> str:
    """回读断言用：返回不合规原因，合规返回空串。"""
    if not data.startswith(BOM):
        return "缺 UTF-8 BOM"
    lf = data.count(b"\n")
    crlf = data.count(b"\r\n")
    if crlf == 0:
        return "纯 LF 换行"
    if crlf != lf:
        return f"换行混杂 LF={lf} CRLF={crlf}"
    return ""


def collect(src):
    """收集要打包的文件（相对路径列表）。"""
    files = []
    for f in TOP_FILES:
        p = os.path.join(src, f)
        if os.path.isfile(p):
            files.append(f)
        else:
            print(f"[warn] 顶层文件缺失，跳过：{f}")
    for d in TOP_DIRS:
        root = os.path.join(src, d)
        if not os.path.isdir(root):
            print(f"[warn] 顶层目录缺失，跳过：{d}")
            continue
        for r, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in fs:
                full = os.path.join(r, fn)
                rel = os.path.relpath(full, src).replace("\\", "/")
                if not should_skip(rel):
                    files.append(rel)
    for d in DATA_KEEP:
        root = os.path.join(src, d)
        if not os.path.isdir(root):
            continue
        for r, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in fs:
                full = os.path.join(r, fn)
                rel = os.path.relpath(full, src).replace("\\", "/")
                if not should_skip(rel):
                    files.append(rel)
    return sorted(set(files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="")
    ap.add_argument("--root-name", default="fangong-workbench",
                    help="解压后的顶层目录名（默认 fangong-workbench）")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    out = os.path.abspath(args.out)
    if not os.path.isdir(src):
        print(f"源目录不存在：{src}")
        return 2

    # 版本号：直接读源里的 config.py，不信文件名/记忆
    ver = ""
    cfg = os.path.join(src, "app", "config.py")
    if os.path.isfile(cfg):
        for line in open(cfg, encoding="utf-8"):
            if line.strip().startswith("APP_VERSION"):
                ver = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    tag = args.tag or ("v" + ver.replace(".", "") if ver else "build")
    print(f"源：{src}")
    print(f"版本：{ver}  标记：{tag}")

    files = collect(src)
    print(f"待打包文件：{len(files)} 个")

    # v0.1.177：出厂前把每个 .bat 规整成 UTF-8 BOM + CRLF（cmd 才能正确执行）
    _bat_fixed = []
    for rel in files:
        if rel.lower().endswith(".bat"):
            if _bat_to_bom_crlf(os.path.join(src, rel)):
                _bat_fixed.append(rel)
    if _bat_fixed:
        print(f"已修正 .bat 编码（UTF-8 BOM + CRLF）：{len(_bat_fixed)} 个 -> {_bat_fixed}")
    else:
        print("全部 .bat 编码已合规（UTF-8 BOM + CRLF）")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    total_raw = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            full = os.path.join(src, rel)
            arc = f"{args.root_name}/{rel}"
            zf.write(full, arc)
            total_raw += os.path.getsize(full)

        # 空的 data/projects 骨架（解压后即存在，省得首启动才创建）
        stub = "data/projects/.keep"
        zf.writestr(f"{args.root_name}/{stub}", "")

        manifest = {
            "version": ver, "tag": tag, "file_count": len(files) + 1,
            "uncompressed_bytes": total_raw, "source": "working tree",
            "generated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        }
        zf.writestr(f"{args.root_name}/PACKAGE_MANIFEST.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))

    # 回读校验：包能不能开、版本号对不对、关键文件在不在
    print("\n回读校验：")
    problems = []
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
        if bad:
            problems.append(f"损坏成员：{bad}")
        names = set(zf.namelist())
        must = [f"{args.root_name}/{x}" for x in
                ("start.py", "app/config.py", "app/main.py", "web/index.html",
                 "requirements.txt", "install.bat", "run_workbench.bat",
                 "tools/selftest.py", "tools/fieldtest.py", "tools/verify_install.py")]
        for m in must:
            if m not in names:
                problems.append(f"缺文件：{m}")
        # 版本号必须与源一致
        try:
            inner = zf.read(f"{args.root_name}/app/config.py").decode("utf-8")
            iv = ""
            for line in inner.splitlines():
                if line.strip().startswith("APP_VERSION"):
                    iv = line.split("=", 1)[1].strip().strip('"').strip("'")
            if iv != ver:
                problems.append(f"包内版本号 {iv} != 源 {ver}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"读包内 config.py 失败：{e}")
        # 不许带进业务数据
        leaked = [n for n in names if n.startswith(f"{args.root_name}/data/projects/") and not n.endswith(".keep")]
        if leaked:
            problems.append(f"包内混入项目业务数据 {len(leaked)} 个：{leaked[:3]}")
        tpl = [n for n in names if n.startswith(f"{args.root_name}/data/templates/")]
        tpl_files = len(tpl)
        # v0.1.177：**断言包内每个 .bat 都是 UTF-8 BOM + CRLF**。
        # 这一条是防回归的：用户端执行不了 .bat，整个安装流程就走不下去，
        # 而这类问题在沙箱 Linux 上跑任何测试都发现不了，只有回读字节才能拦住。
        _bats = [n for n in names if n.lower().endswith(".bat")]
        for _b in sorted(_bats):
            _why = _bat_noncompliant(zf.read(_b))
            if _why:
                problems.append(f".bat 编码不合规：{os.path.basename(_b)}（{_why}）")
        print(f"  .bat 编码检查：{len(_bats)} 个文件")

    size = os.path.getsize(out)
    print(f"  ZIP：{out}")
    print(f"  大小：{size/1024/1024:.1f} MB（原始 {total_raw/1024/1024:.1f} MB，{len(names)} 个成员）")
    print(f"  内置模板库带上：{tpl_files} 个文件")
    if problems:
        for p in problems:
            print(f"  [FAIL] {p}")
        return 1
    print("  [PASS] 包可打开、关键文件齐全、版本号一致、无业务数据泄漏")
    print(f"\n完成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
