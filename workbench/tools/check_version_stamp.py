#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库版本声明唯一性门禁（v0.1.250 新增 / D38）。

背景（真机实测发现）：
    交付链三方核对（包 ↔ 磁盘 ↔ GitHub 远端）报出**唯一一处不一致**：
        包内 PACKAGE_MANIFEST.json : version=0.1.249  file_count=311
        远端 workbench/PACKAGE_MANIFEST.json : version=0.1.205  file_count=270
    远端那份是 **14 个版本前**的残留。仓库对外自称 v0.1.205，代码实际是 0.1.249 ——
    又一个「同一件事两个答案」：版本号有两个来源，其中一个没人维护。

    为什么会漂：PACKAGE_MANIFEST.json 是**构建期生成**的版本戳（写进 zip，
    随包发给使用者），它被当成「只写不读」的文件排除在推送清单之外；
    但历史上它又被提交进仓库 —— 两套规则对同一个文件判断不一致，
    于是仓库里留下了一份永远不会再更新的旧副本。

本门禁锁死四条：
    G1  app/config.py 里的 APP_VERSION 能解析出来，且形如 0.1.NNN。
    G2  **源码树里不允许存在 PACKAGE_MANIFEST.json** —— 它是构建产物，
        只写进 zip。仓库里留着它 = 迟早又变成一份没人更新的假版本声明。
    G3  树里任何 JSON 文件如果自称 version/app_version，必须等于 APP_VERSION。
        （云端子服务 cloud_server 是独立部署的另一个进程，允许自带版本号，
         但它必须在自己文件里只有一个答案，见 G4。）
    G4  cloud_server/app.py：文件头注释里的版本号必须与 FastAPI(version=...) 一致。
    G5  可选 --package <zip>：包内清单的 version 必须等于 APP_VERSION，
        file_count 必须等于包内文件总数（否则清单在骗使用者）。

防「零命中当通过」：
    门禁末尾有一个**自检**：往临时目录里放一份版本号故意写错的 JSON，
    确认扫描器**确实能把它挑出来**。挑不出来 = 扫描器坏了 = 本门禁报红。
    （上一轮 check_scope_calls 就踩过「零命中当通过」的坑。）

跑法：python tools/check_version_stamp.py [--package <实测包.zip>]
退出码：0 = 通过；非 0 = 有不一致。
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 扫描时要跳过的目录：运行期数据与外部素材，不属于「仓库源码」。
SKIP_DIRS = {"__pycache__", "data", "ocrdata", "platform_data", ".git", "node_modules"}
# 扫描时要跳过的文件：测试产物（只被写出、从不被读取）。
ARTIFACT_SUFFIX = ("_report.json", "_report.md")
ARTIFACT_NAMES = {"selftest_cleanup.json", "verify_install.json"}


def app_version(root: str = ROOT) -> str:
    """从 app/config.py 解析 APP_VERSION。"""
    cfg = os.path.join(root, "app", "config.py")
    if not os.path.isfile(cfg):
        return ""
    with open(cfg, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = re.match(r'\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', line)
            if m:
                return m.group(1)
    return ""


def is_artifact(rel: str) -> bool:
    name = rel.replace(os.sep, "/").rsplit("/", 1)[-1]
    if name in ARTIFACT_NAMES:
        return True
    return name.endswith(ARTIFACT_SUFFIX)


def scan_version_markers(root: str) -> list:
    """扫出树里所有自称版本的 JSON 项：返回 [(relpath, key, value), ...]。

    只看 JSON —— 源码里的版本声明由 G1/G4 单独管（Python 里到处是
    "0.1.205" 这种历史注释，不是版本声明）。
    """
    hits = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            if is_artifact(rel):
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    d = json.load(fh)
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            for key in ("version", "app_version"):
                if key in d and isinstance(d[key], (str, int, float)):
                    hits.append((rel.replace(os.sep, "/"), key, str(d[key])))
    return hits


def cloud_server_versions(root: str = ROOT) -> dict:
    """cloud_server/app.py 里的版本声明：文件头注释 与 版本常量。

    v0.1.250：版本号已常量化为 CLOUD_VERSION，FastAPI(version=CLOUD_VERSION)
    不再写死字符串。所以这里必须**跟着改**——门禁写法跟不上实现，
    等于这条断言从没测过（判定「未找到」就跳过 = 静默放过）。
    """
    p = os.path.join(root, "cloud_server", "app.py")
    out = {"header": "", "fastapi": "", "const": "", "path": os.path.relpath(p, root)}
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8", errors="ignore") as fh:
        text = fh.read()
    m = re.search(r'CLOUD_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if m:
        out["const"] = m.group(1)
    m = re.search(r"FastAPI\([^)]*version\s*=\s*([^,)]+)", text, re.S)
    if m:
        out["fastapi"] = m.group(1).strip()
    for line in text.splitlines()[:6]:
        m = re.search(r"（v?([0-9]+\.[0-9]+\.[0-9]+)）", line)
        if m:
            out["header"] = m.group(1)
            break
    return out


def check_package(pkg_path: str, expect_version: str) -> list:
    """校验实测包里的清单与包内容一致。返回问题列表。"""
    problems = []
    if not os.path.isfile(pkg_path):
        return [f"实测包不存在：{pkg_path}"]
    z = zipfile.ZipFile(pkg_path)
    names = [n for n in z.namelist() if not n.endswith("/")]
    mname = None
    for n in names:
        if n.rsplit("/", 1)[-1] == "PACKAGE_MANIFEST.json":
            mname = n
            break
    if not mname:
        problems.append("实测包里没有 PACKAGE_MANIFEST.json（使用者无从判断版本）")
        return problems
    try:
        man = json.loads(z.read(mname).decode("utf-8"))
    except Exception as e:
        problems.append(f"清单读不出来：{e}")
        return problems
    if man.get("version") != expect_version:
        problems.append(f"清单版本 {man.get('version')} != APP_VERSION {expect_version}")
    if int(man.get("file_count") or 0) != len(names):
        problems.append(f"清单 file_count {man.get('file_count')} != 包内文件数 {len(names)}")
    return problems


def main(argv):
    pkg = None
    if "--package" in argv:
        i = argv.index("--package")
        if i + 1 >= len(argv):
            print("FAIL: --package 后面要给 zip 路径")
            return 2
        pkg = argv[i + 1]

    fails = []
    ver = app_version()
    print("== 版本声明唯一性门禁（v0.1.250 / D38）==\n")

    # G1
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver or ""):
        fails.append(f"G1 解析不到合法的 APP_VERSION（读出 {ver!r}）")
        print(f"[FAIL] G1 APP_VERSION 解析: {ver!r}")
    else:
        print(f"[PASS] G1 APP_VERSION = {ver}")

    # G2
    stray = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn == "PACKAGE_MANIFEST.json":
                stray.append(os.path.relpath(os.path.join(dp, fn), ROOT))
    if stray:
        fails.append(f"G2 源码树里存在构建产物 PACKAGE_MANIFEST.json：{stray}（它只应写进 zip）")
        print(f"[FAIL] G2 树内存在 PACKAGE_MANIFEST.json: {stray}")
    else:
        print("[PASS] G2 源码树里没有 PACKAGE_MANIFEST.json")

    # G3
    markers = scan_version_markers(ROOT)
    bad = [(r, k, v) for r, k, v in markers
           if v != ver and not r.startswith("cloud_server" + "/")]
    if bad:
        fails.append(f"G3 自称版本却与 APP_VERSION 不一致：{bad}")
        for r, k, v in bad:
            print(f"[FAIL] G3 {r}: {k}={v} != {ver}")
    else:
        note = "（0 处属正常：版本戳只写进 zip，源码树里本就不该有）" if not markers else ""
        print(f"[PASS] G3 树内 JSON 版本声明一致（扫到 {len(markers)} 处）{note}")

    # G4
    cs = cloud_server_versions()
    if cs["const"] and cs["header"] and cs["const"] != cs["header"]:
        fails.append(f"G4 cloud_server 版本两个答案：文件头 {cs['header']} vs 常量 {cs['const']}")
        print(f"[FAIL] G4 cloud_server 文件头 {cs['header']} != CLOUD_VERSION {cs['const']}")
    elif cs["const"] and cs["fastapi"] and cs["fastapi"] != "CLOUD_VERSION":
        fails.append(f"G4 FastAPI 版本没有用常量（{cs['fastapi']}）—— 会与常量分叉")
        print(f"[FAIL] G4 FastAPI(version={cs['fastapi']}) 未使用 CLOUD_VERSION 常量")
    elif not cs["const"]:
        fails.append("G4 cloud_server/app.py 找不到版本常量 CLOUD_VERSION")
        print("[FAIL] G4 cloud_server/app.py 找不到 CLOUD_VERSION")
    else:
        print(f"[PASS] G4 cloud_server 版本声明唯一（{cs['const']}，文件头一致，FastAPI 引用常量）")

    # G5
    if pkg:
        probs = check_package(pkg, ver)
        if probs:
            fails.extend(probs)
            for p in probs:
                print(f"[FAIL] G5 {p}")
        else:
            print(f"[PASS] G5 实测包清单与包内容、与 APP_VERSION 三者一致")

    # 自检：扫描器本身必须能挑出错版本（防「零命中当通过」）
    tmp = tempfile.mkdtemp(prefix="fg_versionstamp_")
    try:
        os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
        with open(os.path.join(tmp, "sub", "wrong.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": "0.0.1-nope"}, fh)
        probe = scan_version_markers(tmp)
        if not probe:
            fails.append("自检失败：扫描器对一份明显错的版本声明毫无反应（门禁是空门禁）")
            print("[FAIL] 自检 扫描器没挑出错版本 —— 本门禁是空门禁")
        else:
            print(f"[PASS] 自检 扫描器能挑出错版本（{probe[0][2]}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    if fails:
        print(f"结果：通过 {5 - len(fails)} / 失败 {len(fails)}")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("结果：通过 5 / 失败 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
