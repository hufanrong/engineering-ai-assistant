# 繁工AI 本地解析工作台 - 竣工资料自动组卷（v0.1.24）
# 依据 v3.7 口径：资料生成按项目进度推进，生成即存档；组卷按竣工归档目录归卷，
# 卷内目录导出 Excel，缺项列出待补，最终整卷打包 zip 供打印签字。
import datetime
import io
import json
import os
import zipfile

from . import config
from . import docgen

# 卷宗结构：竣工归档常用类目（可扩展）
VOLUMES = [
    {"no": "01", "name": "开工与施工方案", "docs": ["施工方案"]},
    {"no": "02", "name": "吊装与安全专项方案", "docs": ["吊装方案"]},
    {"no": "03", "name": "技术交底", "docs": ["技术交底"]},
    {"no": "04", "name": "设备开箱与隐蔽验收", "docs": ["开箱验收记录", "隐蔽工程验收记录"]},
    {"no": "05", "name": "施工进度计划", "docs": ["施工计划"]},
    {"no": "06", "name": "施工记录", "docs": ["施工日志"]},
    {"no": "07", "name": "变更与签证", "docs": ["设计变更", "货损报告"]},
    {"no": "08", "name": "竣工验收", "docs": ["竣工资料"]},
]


def _gen_dir() -> str:
    d = os.path.join(config.DATA_DIR, "generated_docs")
    os.makedirs(d, exist_ok=True)
    return d


def _save_generated(doc_type: str, content: bytes, devices: list = None, workshops: list = None) -> str:
    """生成文档落盘存档（v0.1.24）：data/generated_docs/{类型}/繁工AI_{类型}_{时间}.docx
    v0.1.39：保存后自动登记设备/车间关联。"""
    tdir = os.path.join(_gen_dir(), doc_type)
    os.makedirs(tdir, exist_ok=True)
    fname = f"繁工AI_{doc_type}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    path = os.path.join(tdir, fname)
    with open(path, "wb") as fh:
        fh.write(content)
    # v0.1.39：自动登记资料关联
    try:
        from . import doc_relations as _dr
        _dr.register_doc(f"{doc_type}/{fname}", doc_type, file_path=path,
                         devices=devices, workshops=workshops, source="generated")
    except Exception:  # noqa: BLE001
        pass
    return path


def _list_generated() -> dict:
    """doc_type -> [文件路径]（按 mtime 倒序）"""
    out = {}
    root = _gen_dir()
    if not os.path.isdir(root):
        return out
    for t in os.listdir(root):
        tdir = os.path.join(root, t)
        if not os.path.isdir(tdir):
            continue
        files = []
        for f in os.listdir(tdir):
            if f.endswith(".docx"):
                p = os.path.join(tdir, f)
                files.append((os.path.getmtime(p), p))
        files.sort(reverse=True)
        out[t] = [p for _, p in files]
    return out


def archive_status() -> dict:
    """每卷：已有资料、缺失类型、卷内清单；统计齐全度。"""
    gen = _list_generated()
    volumes = []
    total_have, total_need = 0, 0
    for v in VOLUMES:
        items = []
        missing = []
        for t in v["docs"]:
            files = gen.get(t, [])
            if files:
                items.append({"doc_type": t, "count": len(files),
                              "latest": os.path.basename(files[0]),
                              "ts": datetime.datetime.fromtimestamp(os.path.getmtime(files[0])).strftime("%Y-%m-%d %H:%M")})
                total_have += 1
            else:
                missing.append(t)
                total_need += 1
        volumes.append({"no": v["no"], "name": v["name"],
                        "docs": v["docs"], "items": items, "missing": missing,
                        "ready": not missing})
    return {
        "volumes": volumes,
        "generated_total": sum(len(f) for f in gen.values()),
        "ready_volumes": sum(1 for v in volumes if v["ready"]),
        "total_volumes": len(VOLUMES),
        "have_types": total_have,
        "need_types": total_have + total_need,
        "latest_build": datetime.datetime.now().isoformat(),
    }


def export_archive() -> bytes:
    """按卷组织生成 zip：卷目录/文件 + 卷内目录.xlsx。"""
    gen = _list_generated()
    buf = io.BytesIO()
    # 卷内目录
    rows = [["卷号", "卷名", "资料类型", "文件", "生成时间", "状态"]]
    for v in VOLUMES:
        for t in v["docs"]:
            files = gen.get(t, [])
            if files:
                for p in files:
                    ts = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
                    rows.append([v["no"], v["name"], t, os.path.basename(p), ts, "已归档"])
            else:
                rows.append([v["no"], v["name"], t, "—", "—", "缺失（待生成）"])
    xlsx = _make_xlsx(rows)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_卷内目录.xlsx", xlsx)
        zf.writestr("README.txt",
                    "繁工AI 竣工资料归档包\n"
                    "导出时间：%s\n"
                    "说明：按卷宗结构组织；缺失项见卷内目录『缺失（待生成）』行，"
                    "在⑧资料生成计划中补齐后重新导出。签字由人工下载打印完成。\n"
                    % datetime.datetime.now().isoformat())
        for v in VOLUMES:
            for t in v["docs"]:
                for p in gen.get(t, []):
                    arc = f"{v['no']}_{v['name']}/{os.path.basename(p)}"
                    zf.write(p, arc)
    return buf.getvalue()


def _make_xlsx(rows: list) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "卷内目录"
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=val)
            c.font = Font(name="微软雅黑", size=10, bold=(i == 1))
            c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for col, w in zip("ABCDEF", [10, 22, 20, 40, 18, 16]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
