# -*- coding: utf-8 -*-
"""
v0.1.131：DWG 竣工图清稿工具桥接模块。

功能：
1. 环境自动检测：操作系统 / AutoCAD 安装与版本 / pywin32 / pypdf / 打印设备
2. 图纸清稿：调用 tools/dwg_cleaner/core.process_file 处理 DWG →
   删除标题栏设计院/人名/日期/“施工图”字样 → 替换为“竣工图” →
   逐图导出并合并 PDF + 另存清稿 DWG（原文件只读，MD5 校验）
3. 竣工资料联动：生成竣工资料前自动检查项目内未清稿图纸并处理

依赖说明（Windows 部署机）：
- AutoCAD 2020+（COM 驱动，必需）
- pywin32（win32com / pythoncom，必需）
- pypdf（PDF 合并，必需）
Linux/无 CAD 环境下所有检测函数可安全调用，process 类函数返回明确错误。
"""

import os
import sys
import json
import datetime
from typing import List, Dict, Optional

# tools/dwg_cleaner 包路径（跨平台延迟导入，无 CAD 机器 import 本模块不报错）
_TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

TOOL_PACKAGE_DIR = os.path.join(_TOOLS_DIR, "dwg_cleaner")
DEFAULT_CONFIG = os.path.join(TOOL_PACKAGE_DIR, "config.json")

# 供前端展示的下载/安装指引
HELP_TEXT = {
    "autocad": "未检测到 AutoCAD。竣工图清稿依赖 AutoCAD 2020 及以上版本（COM 驱动）。"
               "请到 Autodesk 官网下载安装 AutoCAD 2020 或更高版本："
               "https://www.autodesk.com/products/autocad/overview （安装后重启工作台）。",
    "pywin32": "缺少 pywin32（Windows COM 组件）。请在命令提示符执行："
               "pip install pywin32",
    "pypdf": "缺少 pypdf（PDF 合并组件）。请在命令提示符执行："
             "pip install pypdf",
    "windows": "当前系统不是 Windows。竣工图清稿工具仅支持 Windows + AutoCAD "
               "（AutoCAD 无 Linux/macOS 官方版本）。请在 Windows 电脑上部署本工作台使用该功能。",
}


def detect_environment() -> Dict:
    """全面检测清稿工具运行环境。

    Returns:
        {ok, platform, windows, autocad{installed, version}, pywin32,
         pypdf, plot_device, ready, missing[], hint}
    """
    result = {
        "tool": "dwg_cleaner",
        "tool_version": "v1.0",
        "platform": sys.platform,
        "windows": sys.platform.startswith("win"),
        "autocad": {"installed": False, "version": ""},
        "pywin32": False,
        "pypdf": False,
        "plot_device": "DWG To PDF.pc3",
        "ready": False,
        "missing": [],
        "hint": [],
    }

    # 1) 操作系统
    if not result["windows"]:
        result["missing"].append("windows")
        result["hint"].append(HELP_TEXT["windows"])
        return result

    # 2) pywin32
    try:
        import win32com.client  # noqa: F401
        import pythoncom  # noqa: F401
        result["pywin32"] = True
    except Exception:
        result["missing"].append("pywin32")
        result["hint"].append(HELP_TEXT["pywin32"])

    # 3) pypdf
    try:
        import pypdf  # noqa: F401
        result["pypdf"] = True
    except Exception:
        result["missing"].append("pypdf")
        result["hint"].append(HELP_TEXT["pypdf"])

    # 4) AutoCAD（COM Dispatch + 版本）
    if result["pywin32"]:
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                app = win32com.client.Dispatch("AutoCAD.Application")
                try:
                    result["autocad"]["version"] = str(app.Version)
                except Exception:
                    pass
                result["autocad"]["installed"] = True
            except Exception:
                # COM 失败 → 查注册表兜底
                result["autocad"]["installed"] = _autocad_in_registry()
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        except Exception:
            pass

    if not result["autocad"]["installed"]:
        result["missing"].append("autocad")
        result["hint"].append(HELP_TEXT["autocad"])

    # 5) 汇总
    result["ready"] = (
        result["windows"] and result["pywin32"] and result["pypdf"]
        and result["autocad"]["installed"])
    if not result["ready"] and not result["missing"]:
        result["missing"].append("unknown")
        result["hint"].append("环境检测异常，请检查工作台安装完整性后重试。")
    return result


def _autocad_in_registry() -> bool:
    """通过注册表检测 AutoCAD 安装（HKLM\\SOFTWARE\\Autodesk\\AutoCAD）。"""
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(hive, r"SOFTWARE\\Autodesk\\AutoCAD")
                # 存在任意版本键即认为已安装
                try:
                    winreg.QueryInfoKey(key)
                    return True
                finally:
                    winreg.CloseKey(key)
            except OSError:
                continue
    except Exception:
        pass
    return False


def _out_dir_for(project_id: Optional[str] = None) -> str:
    """清稿输出目录：项目 exports/竣工图清稿 或 全局 data/exports/竣工图清稿。"""
    try:
        from . import project_manager as _pm
        if project_id:
            pdir = _pm.get_project_exports_dir(project_id)
        else:
            pdir = _pm.get_project_exports_dir()
        out = os.path.join(pdir, "竣工图清稿")
    except Exception:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "exports")
        out = os.path.join(base, "竣工图清稿")
    os.makedirs(out, exist_ok=True)
    return out


def list_project_drawings(project_id: Optional[str] = None) -> List[Dict]:
    """列出当前/指定项目内已入库的 DWG/DXF 图纸文件。"""
    drawings = []
    try:
        from . import project_manager as _pm
        index_path = _pm.get_project_index_path(project_id)
        with open(index_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        # 兼容两种索引结构：{sha256: {...}}（扫描后） 或 {files: [...]}（新建初始化）
        if isinstance(idx, dict) and "files" in idx and not any(
                k for k in idx if len(str(k)) == 64):
            files = idx.get("files", [])
        elif isinstance(idx, dict):
            files = list(idx.values())
        else:
            files = []
        for f in files:
            if not isinstance(f, dict):
                continue
            name = f.get("file_name", "")
            if name.lower().endswith((".dwg", ".dxf")):
                drawings.append({
                    "file_name": name,
                    "file_path": f.get("file_path", ""),
                    "sha256": f.get("sha256", ""),
                    "status": f.get("status", ""),
                })
    except Exception:
        pass
    return drawings


def process_dwg_file(dwg_path: str, out_dir: Optional[str] = None,
                     project_id: Optional[str] = None) -> Dict:
    """处理单个 DWG：环境检查 → 调 core.process_file。

    out_dir 为空时输出到项目 exports/竣工图清稿/{图名}/。
    """
    env = detect_environment()
    if not env["ready"]:
        return {
            "status": "failed",
            "file": dwg_path,
            "error": "；".join(env["missing"]) or "环境未就绪",
            "hint": env["hint"],
            "env": env,
        }
    if not os.path.isfile(dwg_path):
        return {"status": "failed", "file": dwg_path, "error": "文件不存在"}

    out = out_dir or _out_dir_for(project_id)
    try:
        from dwg_cleaner import core, rules
        cfg = rules.load_config(DEFAULT_CONFIG)
        result = core.process_file(dwg_path, out, cfg)
        result["env"] = None
        return result
    except Exception as e:  # noqa: BLE001
        return {
            "status": "failed",
            "file": dwg_path,
            "error": f"{type(e).__name__}: {e}",
            "hint": env["hint"],
        }


def process_drawings(dwg_paths: List[str], out_dir: Optional[str] = None,
                     project_id: Optional[str] = None) -> Dict:
    """批量处理图纸：返回 {total, success, failed, results[]}。"""
    env = detect_environment()
    if not env["ready"]:
        return {
            "status": "failed", "total": 0, "success": 0, "failed": 0,
            "results": [],
            "error": "；".join(env["missing"]) or "环境未就绪",
            "hint": env["hint"],
        }
    out = out_dir or _out_dir_for(project_id)
    results = []
    success = failed = 0
    for p in dwg_paths:
        r = process_dwg_file(p, out, project_id)
        r.pop("env", None)
        results.append(r)
        if r.get("status") == "success":
            success += 1
        else:
            failed += 1
    return {
        "status": "done",
        "total": len(dwg_paths), "success": success, "failed": failed,
        "results": results, "out_dir": out,
    }


def ensure_completion_drawings(project_id: Optional[str] = None) -> Dict:
    """竣工资料联动入口：生成竣工资料前调用。

    检查项目内未清稿 DWG → 环境就绪则自动清稿；否则返回 missing 提示，
    由调用方（前端/竣工组卷）提示用户补装工具。
    """
    drawings = list_project_drawings(project_id)
    if not drawings:
        return {"status": "no_drawings", "message": "项目内没有 DWG/DXF 图纸，无需清稿", "total": 0}
    env = detect_environment()
    if not env["ready"]:
        return {
            "status": "env_missing",
            "message": "检测到需要清稿的图纸，但清稿工具环境不全",
            "total": len(drawings),
            "missing": env["missing"],
            "hint": env["hint"],
        }
    paths = [d["file_path"] for d in drawings if d.get("file_path")]
    return process_drawings(paths, project_id=project_id)


def help_text() -> Dict:
    """下载/安装指引（供前端展示）。"""
    env = detect_environment()
    return {
        "ok": True,
        "tool": "DWG 竣工图清稿工具 v1.0",
        "ready": env["ready"],
        "missing": env["missing"],
        "hint": env["hint"] or ["环境已就绪，可直接使用"],
        "requirements": [
            {"name": "AutoCAD 2020+", "need": "必需（COM 驱动打开/修改/打印）", "action": "Autodesk 官网下载安装"},
            {"name": "pywin32", "need": "必需（Windows COM）", "action": "pip install pywin32"},
            {"name": "pypdf", "need": "必需（PDF 合并）", "action": "pip install pypdf"},
        ],
        "checked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
