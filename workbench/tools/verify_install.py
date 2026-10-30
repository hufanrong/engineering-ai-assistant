#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""繁工AI 安装后自检 · 装完先跑这个，再跑 fieldtest.py。

用法（在 workbench 目录下，**服务未启动也可以跑**）：

    python tools\\verify_install.py
    python tools\\verify_install.py --base http://127.0.0.1:8756   # 服务已在跑，额外验证在线状态

只做「装得对不对」这一件事：Python 版本、依赖是否真能 import、版本号是否一致、
内置模板是否齐全、数据目录是否可写、端口是否可用。不做业务操作（那是 fieldtest.py）。

输出：
  - 屏幕上一行一条 [PASS]/[FAIL]/[SKIP]
  - verify_install.json（同目录），字段固定，便于回传后自动比对
退出码：0 = 全部通过（有 SKIP 不算失败）；1 = 有 FAIL。
"""

import argparse
import importlib.util
import json
import os
import platform
import socket
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
WB_DIR = os.path.dirname(HERE)          # workbench/
ROOT = os.path.dirname(WB_DIR)          # 仓库根
RESULTS = []


def rec(step, expected, actual, passed, evidence=""):
    RESULTS.append({
        "step": step, "expected": expected, "actual": actual,
        "passed": passed, "evidence": evidence,
    })
    tag = "SKIP" if passed is None else ("PASS" if passed else "FAIL")
    print(f"  [{tag}] {step}: {actual}" + (f" | {evidence}" if evidence and not passed else ""))


def parse_version(v):
    """把 '0.1.173' 解析成 (0,1,173)；解析不出来返回 None（不猜）。"""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return None


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 9)
    rec("Python 版本", ">= 3.9（推荐 3.10~3.12）", f"{v.major}.{v.minor}.{v.micro}", ok,
        "低于 3.9 的版本 chromadb / sentence-transformers 无可用轮子")
    return ok


def check_deps():
    """逐个 import 核心依赖。返回缺失清单，供后续提示。"""
    core = [
        ("fastapi", "Web 框架"),
        ("uvicorn", "服务容器"),
        ("multipart", "上传（python-multipart）"),
        ("requests", "HTTP 客户端"),
        ("pypdf", "PDF 文本"),
        ("pdfplumber", "PDF 表格"),
        ("docx", "Word 解析/生成（python-docx）"),
        ("openpyxl", "Excel 台账"),
        ("tqdm", "进度条"),
    ]
    optional = [
        ("sentence_transformers", "向量语义检索（不装则降级关键词检索）"),
        ("chromadb", "向量库（不装则降级关键词检索）"),
        ("ezdxf", "CAD 解析（不装则图纸只登记不解析）"),
        ("paddleocr", "图片 OCR（不装则图片只登记）"),
        ("win32com", "DWG 清稿（仅 Windows + Office/CAD 需要）"),
    ]
    missing_core, missing_opt = [], []
    for mod, desc in core:
        found = importlib.util.find_spec(mod) is not None
        if not found:
            missing_core.append(f"{mod}({desc})")
    for mod, desc in optional:
        if importlib.util.find_spec(mod) is None:
            missing_opt.append(f"{mod}({desc})")

    rec("核心依赖完整", "全部可 import", f"缺失 {len(missing_core)} 项" + (f"：{missing_core}" if missing_core else ""),
        not missing_core, "缺失核心依赖会让对应接口 500，必须装齐")
    rec("可选依赖", "缺失不影响启动（仅降级对应能力）",
        f"缺失 {len(missing_opt)} 项" + (f"：{missing_opt}" if missing_opt else "，已全装"),
        None, "降级是设计内的行为，不算失败")
    return missing_core


def check_version():
    """版本号必须三处一致：config.APP_VERSION、FastAPI app.version、包目录名/清单。"""
    sys.path.insert(0, WB_DIR)
    try:
        from app import config
        from app.main import app as fastapi_app
    except Exception as e:  # noqa: BLE001
        rec("代码可导入", "app.main 能 import", f"{type(e).__name__}: {e}", False,
            traceback.format_exc()[-400:])
        return None
    cfg_v = getattr(config, "APP_VERSION", "")
    api_v = getattr(fastapi_app, "version", "")
    rec("版本号一致", "config.APP_VERSION == FastAPI version",
        f"config={cfg_v} api={api_v}", cfg_v == api_v and bool(cfg_v))
    return cfg_v


def check_templates():
    """内置监理模板必须齐全（缺了整卷会静默出空壳）。数模板文件数，不靠记忆。"""
    d = os.path.join(WB_DIR, "templates_builtin")
    if not os.path.isdir(d):
        rec("内置模板目录", "templates_builtin 存在", "目录不存在", False, f"期望在 {d}")
        return 0
    files = [f for f in os.listdir(d) if f.lower().endswith((".docx", ".xlsx"))]
    idx = os.path.join(d, "_table_index.json")
    rec("内置模板齐全", ">= 100 个 docx/xlsx 模板 + _table_index.json",
        f"{len(files)} 个模板，_table_index.json {'有' if os.path.isfile(idx) else '无'}",
        len(files) >= 100 and os.path.isfile(idx))
    return len(files)


def check_dirs():
    """数据目录必须可写；不可写时上传/生成全废，必须在装完就暴露。"""
    data = os.path.join(WB_DIR, "data")
    os.makedirs(data, exist_ok=True)
    probe = os.path.join(data, ".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        writable = True
        err = ""
    except Exception as e:  # noqa: BLE001
        writable, err = False, f"{type(e).__name__}: {e}"
    rec("数据目录可写", "能在 data/ 下建文件", "可写" if writable else f"不可写 {err}", writable,
        "常见原因：装在 C:\\Program Files 下无权限、或目录被只读挂载")

    # 项目目录脚手架
    pj = os.path.join(data, "projects")
    os.makedirs(pj, exist_ok=True)
    rec("项目目录就绪", "data/projects 存在", "存在" if os.path.isdir(pj) else "缺失",
        os.path.isdir(pj))

    # 路径含中文/空格：工地常见（D:\\工程 资料）。不检查会到运行期才炸。
    weird = os.path.join(data, "目录 空格测试")
    try:
        os.makedirs(weird, exist_ok=True)
        p = os.path.join(weird, "中文 文件名.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("测试")
        os.remove(p)
        os.rmdir(weird)
        ok_weird = True
        err_w = ""
    except Exception as e:  # noqa: BLE001
        ok_weird, err_w = False, f"{type(e).__name__}: {e}"
    rec("中文与空格路径", "能建目录并写中文文件名", "通过" if ok_weird else f"失败 {err_w}", ok_weird)


def check_port(port=8756):
    s = socket.socket()
    s.settimeout(1.5)
    busy = False
    try:
        busy = s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        busy = False
    finally:
        s.close()
    rec("端口状态", f"端口 {port} 可用 或 服务已在跑（都算正常）",
        "已被占用/服务已在运行" if busy else "空闲", None,
        "被占用时确认是不是上一次没关掉的工作台；不是的话改 app/config.py 的 PORT")
    return busy


def check_online(base):
    """服务已启动时，验证接口真的活着、页面真的是完整页面。"""
    import urllib.request
    import urllib.error

    def get(path):
        try:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:  # noqa: BLE001
            return -1, str(e).encode()

    code, raw = get("/api/status")
    try:
        body = json.loads(raw)
    except Exception:
        body = {}
    rec("在线健康检查", "GET /api/status 200 且 version 非空",
        f"{code} version={body.get('version')}", code == 200 and bool(body.get("version")),
        str(body)[:200] if code != 200 else "")

    code, raw = get("/")
    html = raw.decode("utf-8", "replace") if code == 200 else ""
    # 页面必须是完整页面：有 <html>、有实际体积。空白页/错误页也是 200。
    # v0.1.177：阈值**按随包 web/index.html 的真实大小推导**，不再写死 200000。
    # 实测事故：包里的 index.html 是 193830 字节，服务端返回的长度完全一致
    # （说明首页完全正常），却被硬阈值判成「可能是错误页」→ 报告里多一条假 FAIL，
    # 把真正的问题淹掉。取随包体积的 80% 作为下限，既容忍 gzip/压缩差异，
    # 又能拦住返回空壳/错误页的情况。
    try:
        _home = os.path.join(WB_DIR, "web", "index.html")
        _expect = os.path.getsize(_home)
    except Exception:
        _expect = 0
    _floor = int(_expect * 0.8) if _expect else 20_000
    rec("首页可打开", f"200 且返回完整 HTML（>= 随包 index.html 的 80%，下限 {_floor}）",
        f"{code} bytes={len(raw)} 随包={_expect}",
        code == 200 and len(raw) >= _floor and "<html" in html.lower(),
        f"体积仅 {len(raw)} 字节（随包 {_expect}），可能是错误页" if code == 200 and len(raw) < _floor else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="", help="服务地址，给了就额外做在线检查")
    ap.add_argument("--port", type=int, default=8756)
    args = ap.parse_args()

    print("=" * 62)
    print("繁工AI 安装后自检")
    print("=" * 62)
    print(f"  安装目录：{WB_DIR}")
    print(f"  解释器  ：{sys.executable}")
    print(f"  系统    ：{platform.platform()}")
    print()

    print("[1] 运行环境")
    py_ok = check_python()
    print("[2] 依赖")
    missing_core = check_deps()
    print("[3] 版本")
    ver = check_version()
    print("[4] 模板与目录")
    n_tpl = check_templates()
    check_dirs()
    print("[5] 端口")
    check_port(args.port)
    if args.base:
        print("[6] 在线检查")
        check_online(args.base)

    passed = sum(1 for r in RESULTS if r["passed"] is True)
    failed = sum(1 for r in RESULTS if r["passed"] is False)
    skipped = sum(1 for r in RESULTS if r["passed"] is None)

    out = {
        "tool": "verify_install",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "install_dir": WB_DIR,
        "python": sys.version,
        "python_exe": sys.executable,
        "platform": platform.platform(),
        "version": ver,
        "template_count": n_tpl,
        "missing_core_deps": missing_core,
        "summary": {"passed": passed, "failed": failed, "skipped": skipped},
        "checks": RESULTS,
    }
    p = os.path.join(HERE, "verify_install.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    print(f"结果：通过 {passed} / 失败 {failed} / 跳过 {skipped}")
    print(f"报告：{p}")
    if py_ok and not missing_core and failed == 0:
        print("安装自检通过，可以启动 run_workbench.bat")
        return 0
    print("安装自检未通过，先处理上面的 FAIL 再启动")
    return 1


if __name__ == "__main__":
    sys.exit(main())
