# -*- coding: utf-8 -*-
"""
整编联动模块：按整编要求 214 项（229 行）对项目做竣工资料整卷、缺项检查、待办导出
- registry: 固化整编要求（册/序号/名称/表号/A-B-C-DUP 分类/阶段）
- volume_status: 某册×某车间 已生成 / 缺项 / 归集项
- generate_volume: 一键整卷（A 全自动 + B 预填结构 + C 建归集目录）
- export_todo: 待补字段清单导出
"""
import os, json, re
from . import supervision_templates as st

REG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
REG_FILE = os.path.join(REG_DIR, 'supervision_registry.json')

BOOK_ALIAS = {
    '变配电室/总降': '变配电',
    '车间电气': '车间电气',
    '车间仪表': '车间仪表',
    '设备安装': '设备安装',
    '工艺管道': '工艺管道',
}
# 归集类特判（监理表/影像等，即使标 B 也按归集）
COLLECT_ONLY = {'监理旁站记录'}


def _clean_book(book):
    b = (book or '').replace('竣工资料', '').strip()
    return BOOK_ALIAS.get(b, b)


def load_registry():
    """读整编要求登记表。文件缺失/损坏时返回 []（调用方需自行判断并明确报错）。"""
    if not os.path.exists(REG_FILE):
        return []
    try:
        with open(REG_FILE, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


# v0.1.167：登记表缺失时的统一判定 —— 原来 load_registry() 静默返回 []，
# generate_volume 拿到空清单后仍然 ok=True / generated=[] / todo=[]，
# 用户点「一键整卷」看到成功却什么都没产出；route_uploaded_file 同样是静默空转。
def registry_ready() -> bool:
    """整编要求登记表是否可用（非空且条目结构完整）。"""
    reg = load_registry()
    if not reg:
        return False
    return all(isinstance(it, dict) and it.get("名称") for it in reg)


def _book_items(book):
    b = _clean_book(book)
    return [it for it in load_registry() if _clean_book(it.get('册')) == b]


def _item_category(it):
    """项 → 模板类别（映射失败返回 None）"""
    cls = it.get('分类')
    if cls == 'DUP':
        return None
    name = (it.get('名称') or '').strip()
    if cls == 'C' or name in COLLECT_ONLY or any(k in name for k in ['监理旁站', '影像', '照片']):
        return 'C'
    cat = st._categorize(name)
    return cat if cat != '其他' else None


def volume_status(project_id, book, workshop=''):
    """检查某册整编完成度"""
    items = _book_items(book)
    out = {'book': _clean_book(book), 'total': len(items), 'a': 0, 'b': 0, 'c': 0, 'dup': 0,
           'generated': [], 'missing': [], 'collect': [], 'dup_items': []}
    for it in items:
        cls = it.get('分类')
        cat = _item_category(it)
        if cls == 'DUP':
            out['dup'] += 1
            out['dup_items'].append(it.get('序号'))
            continue
        if cat == 'C':
            out['c'] += 1
            out['collect'].append({'序号': it.get('序号'), '名称': it.get('名称')})
            continue
        if cls == 'A':
            out['a'] += 1
        else:
            out['b'] += 1
        # 检查是否已生成（卷目录里有同名文件）
        if cat:
            exists = _check_generated(project_id, book, workshop, it, cat)
            if exists:
                out['generated'].append({'序号': it.get('序号'), '名称': it.get('名称'), '类别': cat})
            else:
                out['missing'].append({'序号': it.get('序号'), '名称': it.get('名称'), '类别': cat, '分类': cls})
    return out


def _check_generated(project_id, book, workshop, it, cat):
    vol = _volume_dir(project_id, book, workshop)
    if not os.path.isdir(vol):
        return False
    prefix = str(it.get('序号')).replace('.', '_')
    for f in os.listdir(vol):
        if f.startswith(prefix + '_'):
            return True
    return False


def _proj_root(project_id):
    """项目数据根：由模板目录推导（workspace/fangong-workbench/templates_builtin → ../data/projects）"""
    wb_root = os.path.dirname(st._te.TEMPLATES_DIR)
    return os.path.join(wb_root, 'projects', project_id)


def _volume_dir(project_id, book, workshop):
    vol = os.path.join(_proj_root(project_id), 'volumes', _clean_book(book), workshop or '全厂')
    return vol


def generate_volume(project_id, book, workshop=''):
    """一键整卷：A 类全自动生成、B 类生成（待补列清单）、C 类建归集目录"""
    items = _book_items(book)
    # v0.1.167：登记表缺失时明确报错，不再返回「成功但什么都没生成」
    if not registry_ready():
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [],
                'error': '整编要求登记表不存在或为空，无法整卷',
                'missing_registry': REG_FILE,
                'hint': '请先把整编要求登记表放到该路径（字段：册/序号/名称/表号/分类/阶段）'}
    if not items:
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [],
                'error': f'整编要求登记表中没有「{_clean_book(book)}」这一册的条目',
                'book': _clean_book(book),
                'available_books': sorted({_clean_book(it.get('册')) for it in load_registry() if it.get('册')})}
    vol = _volume_dir(project_id, book, workshop)
    os.makedirs(vol, exist_ok=True)
    results = {'ok': True, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': []}
    todo_fields = []
    for it in items:
        cls = it.get('分类')
        if cls == 'DUP':
            continue
        cat = _item_category(it)
        seq = str(it.get('序号')).replace('.', '_')
        name = (it.get('名称') or '').strip()
        if cat == 'C':
            d = os.path.join(vol, '_归集_' + seq + '_' + re.sub(r'[\\/:*?"<>|]', '', name)[:40])
            os.makedirs(d, exist_ok=True)
            results['collect_dir'].append(d)
            continue
        if not cat:
            results['errors'].append({'序号': seq, '名称': name, '原因': '无匹配模板'})
            results['todo'].append({'序号': seq, '名称': name, '原因': '模板未建，需人工处理'})
            continue
        r = st.generate_batch(category=cat, workshop=workshop or '全厂', project_id=project_id)
        if not r.get('ok'):
            results['errors'].append({'序号': seq, '名称': name, '原因': r.get('error')})
            continue
        # 移动生成文件到卷目录
        src = os.path.join(_proj_root(project_id), 'exports', r['output_file'])
        _safe_name = re.sub(r'[\\/:*?"<>|]', '', name)[:50]
        dst = os.path.join(vol, f'{seq}_{_safe_name}.docx')
        if os.path.exists(src):
            os.replace(src, dst)
        results['generated'].append({'序号': seq, '名称': name, '文件': os.path.basename(dst)})
        uf = r.get('unfilled_fields') or []
        if uf:
            todo_fields.append({'序号': seq, '名称': name, '待补字段': uf})
    results['todo_fields'] = todo_fields
    # 写待办清单
    todo_md = _render_todo(todo_fields, results['todo'], results['errors'])
    todo_path = os.path.join(vol, '_待办清单.md')
    with open(todo_path, 'w', encoding='utf-8') as f:
        f.write(todo_md)
    results['todo_file'] = todo_path
    results['ok'] = not results['errors']
    return results


def _render_todo(todo_fields, todos, errors):
    lines = ['# 整编待办清单', '', f'生成时间：{__import__("datetime").datetime.now():%Y-%m-%d %H:%M}', '']
    if todo_fields:
        lines.append('## 一、B 类预填，待人工补充实测数据')
        for t in todo_fields:
            lines.append(f"- {t['序号']} {t['名称']}")
            lines.append(f"  待补：{'、'.join(t['待补字段'][:12])}")
    if todos:
        lines.append('## 二、无模板/需人工处理')
        for t in todos:
            lines.append(f"- {t['序号']} {t['名称']}：{t.get('原因')}")
    if errors:
        lines.append('## 三、生成失败')
        for t in errors:
            lines.append(f"- {t['序号']} {t['名称']}：{t.get('原因')}")
    if not todo_fields and not todos and not errors:
        lines.append('（无待办项，全部完成）')
    return '\n'.join(lines)


def export_todo(project_id, book, workshop=''):
    """导出某册待办清单"""
    vol = _volume_dir(project_id, book, workshop)
    path = os.path.join(vol, '_待办清单.md')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return f.read()
    return '（尚未整卷生成，无可导出待办）'


# ---------- C 类文件自动归集（v0.1.152） ----------
# C 类项关键词表：按"文件名关键词 → (册, 序号前缀, 归集名)"，匹配顺序=列表顺序
COLLECT_KEYWORDS = [
    # 变配电 2.x 竣工图
    ("主接线", "变配电室/总降", "2_01", "一次主接线竣工图"),
    ("平面布置", "变配电室/总降", "2_02", "平面布置竣工图"),
    ("二次原理", "变配电室/总降", "2_03", "二次原理竣工图"),
    ("端子接线", "变配电室/总降", "2_04", "二次端子接线竣工图"),
    ("电缆走向", "变配电室/总降", "2_05", "电缆走向竣工图、电缆清册"),
    ("电缆清册", "变配电室/总降", "2_05", "电缆走向竣工图、电缆清册"),
    ("接地网", "变配电室/总降", "2_06", "接地网竣工图"),
    ("直流系统", "变配电室/总降", "2_07", "直流系统竣工图"),
    # 变配电 5.x 厂家资料
    ("工器具", "变配电室/总降", "6_01", "高压安全工器具检测报告"),
    ("验电器", "变配电室/总降", "6_01", "高压安全工器具检测报告"),
    ("绝缘手套", "变配电室/总降", "6_01", "高压安全工器具检测报告"),
    # 电气 2.x
    ("动力系统", "车间电气", "2_01", "车间动力系统竣工图"),
    ("动力平面", "车间电气", "2_02", "车间动力平面布置竣工图"),
    ("照明", "车间电气", "2_03", "车间照明竣工图"),
    ("电缆敷设", "车间电气", "2_04", "车间电缆敷设竣工图"),
    ("电机接线", "车间电气", "2_05", "电机接线竣工图"),
    ("等电位", "车间电气", "2_06", "等电位、防静电接地竣工图"),
    ("防静电", "车间电气", "2_06", "等电位、防静电接地竣工图"),
    ("防爆合格证", "车间电气", "5_02", "防爆设备防爆合格证"),
    # 仪表 2.x
    ("P&ID", "车间仪表", "2_01", "管道及仪表流程图P&ID"),
    ("PID", "车间仪表", "2_01", "管道及仪表流程图P&ID"),
    ("仪表位置", "车间仪表", "2_02", "仪表位置平面竣工图"),
    ("仪表盘柜布置", "车间仪表", "2_03", "仪表盘、柜布置竣工图"),
    ("回路接线", "车间仪表", "2_04", "仪表回路接线图、端子图"),
    ("端子图", "车间仪表", "2_04", "仪表回路接线图、端子图"),
    ("取源部件位置", "车间仪表", "2_06", "取源部件位置竣工图"),
    ("气源", "车间仪表", "2_07", "仪表气源、导压管路竣工图"),
    ("导压管路", "车间仪表", "2_07", "仪表气源、导压管路竣工图"),
    ("联锁逻辑", "车间仪表", "2_08", "联锁逻辑竣工图"),
    ("DCS", "车间仪表", "5_02", "DCS/PLC程序、画面、历史库备份"),
    ("PLC", "车间仪表", "5_02", "DCS/PLC程序、画面、历史库备份"),
    # 通用厂家资料
    ("说明书", None, "厂家资料", "设备原厂说明书、操作手册"),
    ("操作手册", None, "厂家资料", "设备原厂说明书、操作手册"),
    ("合格证", None, "厂家资料", "设备材料出厂合格证、质保书"),
    ("质保书", None, "厂家资料", "设备材料出厂合格证、质保书"),
    ("3C", None, "厂家资料", "设备材料出厂合格证、质保书"),
    ("出厂试验", None, "厂家资料", "设备材料出厂试验报告"),
    ("出厂检测", None, "厂家资料", "设备材料出厂检测报告"),
    ("标定证书", None, "厂家资料", "仪表标定证书"),
    ("检测报告", None, "检测报告", "第三方检测报告"),
    ("检验报告", None, "检测报告", "第三方检测报告"),
]


def _match_collect(file_name):
    for kw, book, seq, name in COLLECT_KEYWORDS:
        if kw in file_name:
            return book, seq, name
    return None


def route_uploaded_file(project_id, file_name, sha256, uploader="", book=None, workshop=""):
    """上传解析完成后自动归集：匹配 C 类项 → 写入归集目录 _collect.json 关联记录。
    返回归集结果；不匹配则返回 None（不做强归集，避免误判）。"""
    try:
        ext = os.path.splitext(file_name)[1].lower()
        is_drawing = ext in ('.dwg', '.dxf', '.dwt')
        m = _match_collect(file_name)
        if not m:
            # 图纸类兜底：cad 图纸无关键词 → 归"图纸通用"
            if is_drawing:
                m = (None, '图纸通用', 'CAD图纸文件')
            else:
                return {"matched": False}
        mbook, seq, name = m
        target_book = book or (mbook if mbook else '未分册')
        base = os.path.join(_volume_dir(project_id, target_book, workshop), f'_归集_{seq}_{name}')
        os.makedirs(base, exist_ok=True)
        rec_path = os.path.join(base, '_collect.json')
        recs = []
        if os.path.exists(rec_path):
            with open(rec_path, encoding='utf-8') as f:
                try:
                    recs = json.load(f)
                except Exception:  # noqa: BLE001
                    recs = []
        if not any(r.get('sha256') == sha256 for r in recs):
            recs.append({"file_name": file_name, "sha256": sha256, "ts": __import__("datetime").datetime.now().isoformat(), "uploader": uploader})
            with open(rec_path, 'w', encoding='utf-8') as f:
                json.dump(recs, f, ensure_ascii=False, indent=1)
        return {"matched": True, "book": target_book, "seq": seq, "name": name, "dir": base}
    except Exception as e:  # noqa: BLE001
        return {"matched": False, "error": str(e)}


def manual_collect(project_id, sha256, book, workshop="", note=""):
    """手动归集：把已入库文件（sha）关联到指定册×指定归集项。
    book 支持 '册|归集项名' 或直接册名（归集到该册通用目录）。"""
    # 从全局解析索引找文件信息（与上传/扫描共用）
    file_name = sha256[:12] + '.bin'
    try:
        from . import scanner
        ent = scanner._load_index().get(sha256) or {}
        file_name = ent.get('file_name', sha256[:12]) or file_name
    except Exception:  # noqa: BLE001
        pass
    if '|' in book:
        mbook, mname = book.split('|', 1)
        seq = '手'
        name = mname
    else:
        mbook, seq, name = book, '手', '手动归集'
    base = os.path.join(_volume_dir(project_id, mbook, workshop), f'_归集_{seq}_{name}')
    os.makedirs(base, exist_ok=True)
    rec_path = os.path.join(base, '_collect.json')
    recs = []
    if os.path.exists(rec_path):
        try:
            recs = json.load(open(rec_path, encoding='utf-8'))
        except Exception:  # noqa: BLE001
            recs = []
    recs.append({"file_name": file_name, "sha256": sha256, "ts": __import__("datetime").datetime.now().isoformat(), "note": note})
    json.dump(recs, open(rec_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {"ok": True, "dir": base, "recs": len(recs)}


# ---------------- 整编要求登记表导入（v0.1.168） ----------------
# 背景：整卷生成依赖《整编要求登记表》（册/序号/名称/表号/分类/阶段，214 项），
# 但仓库和设计文档里都没有这个文件，也没有任何上传入口 —— 用户即使拿到原件也无处导入，
# 整卷生成会一直停在「登记表不存在」。这里补齐导入/查询/校验三个入口。
#
# 接受两种来源：JSON（[{册,序号,名称,表号,分类,阶段}] 或 {"items":[...]}）与 Excel
# （首行表头，列名同字段名，支持常见别名如「图册/资料名称/归档分类」）。

_REG_FIELDS = ["册", "序号", "名称", "表号", "分类", "阶段"]
_REG_ALIAS = {
    "图册": "册", "资料册": "册", "卷册": "册", "册别": "册",
    "顺序": "序号", "编号": "序号", "项次": "序号",
    "资料名称": "名称", "表格名称": "名称", "文件名称": "名称", "名称": "名称",
    "表格编号": "表号", "表号": "表号", "编号表号": "表号",
    "归档分类": "分类", "类别": "分类", "分类": "分类", "等级": "分类",
    "阶段": "阶段", "所属阶段": "阶段", "施工阶段": "阶段",
}


def _normalize_item(raw: dict) -> dict:
    """把一行原始记录规整成标准字段；未知列丢弃，空值给空串。"""
    out = {f: "" for f in _REG_FIELDS}
    for k, v in (raw or {}).items():
        key = str(k).strip()
        fld = key if key in _REG_FIELDS else _REG_ALIAS.get(key)
        if not fld:
            continue
        val = "" if v is None else str(v).strip()
        if val and not out[fld]:
            out[fld] = val
    return out


def _parse_registry_excel(content: bytes) -> list:
    """解析 Excel 登记表。需要 openpyxl；不可用时明确报错而不是静默返回空。"""
    try:
        import io
        import openpyxl
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"缺少 openpyxl，无法解析 Excel：{e}")
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [("" if c is None else str(c).strip()) for c in rows[0]]
    items = []
    for r in rows[1:]:
        if r is None:
            continue
        rec = {}
        for h, v in zip(header, r):
            if h:
                rec[h] = v
        it = _normalize_item(rec)
        # 名称与册都为空视为空行，跳过
        if it["名称"] or it["册"]:
            items.append(it)
    return items


def registry_info() -> dict:
    """登记表状态：是否存在 / 条目数 / 册分布 / 字段完整度。供接口与前端展示。"""
    items = load_registry()
    books = {}
    incomplete = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        b = _clean_book(it.get("册")) or "（未标册）"
        books[b] = books.get(b, 0) + 1
        if not it.get("名称") or not str(it.get("序号") or "").strip():
            incomplete += 1
    return {
        "ready": registry_ready(),
        "path": REG_FILE,
        "exists": os.path.exists(REG_FILE),
        "total": len(items),
        "books": dict(sorted(books.items(), key=lambda kv: -kv[1])),
        "incomplete_items": incomplete,
        "fields": _REG_FIELDS,
    }


def save_registry(items: list) -> dict:
    """校验并落盘登记表。空表 / 全无效条目一律拒绝，避免写出一个"看起来存在"的空登记表。"""
    clean = [_normalize_item(it) for it in items if isinstance(it, dict)]
    clean = [it for it in clean if it["名称"]]
    if not clean:
        return {"ok": False, "error": "登记表没有任何含「名称」的有效条目，已拒绝写入"}
    bad = [i for i, it in enumerate(clean) if not it["册"]]
    os.makedirs(REG_DIR, exist_ok=True)
    # 已有文件先备份，避免反复导入覆盖掉正确版本且无法回退
    if os.path.exists(REG_FILE):
        try:
            import shutil
            shutil.copy2(REG_FILE, REG_FILE + ".bak")
        except Exception:  # noqa: BLE001
            pass
    with open(REG_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    info = registry_info()
    info.update({"ok": True, "imported": len(clean), "items_without_book": len(bad)})
    return info


def import_registry_file(filename: str, content: bytes) -> dict:
    """按扩展名分流导入：.json / .xlsx / .xls / .csv。"""
    name = (filename or "").lower()
    try:
        if name.endswith(".json"):
            data = json.loads(content.decode("utf-8-sig"))
            if isinstance(data, dict):
                data = data.get("items") or data.get("data") or []
            if not isinstance(data, list):
                return {"ok": False, "error": "JSON 结构不认识：需要数组或 {\"items\": [...]}"}
            return save_registry(data)
        if name.endswith((".xlsx", ".xlsm")):
            return save_registry(_parse_registry_excel(content))
        if name.endswith(".csv"):
            import csv
            import io
            text = content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
            return save_registry(rows)
        return {"ok": False, "error": f"不支持的文件类型：{filename}，请用 .json / .xlsx / .csv"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"解析失败：{e}"}
