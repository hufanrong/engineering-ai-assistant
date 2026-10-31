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

# v0.1.173：整编要求登记表改为「按项目存放」。
# 原来固定写在代码目录 app/data/supervision_registry.json —— 全机器只有一份，
# 换项目后还在用上一个项目的监理登记表；而且 app/data 在 .gitignore 的 data/ 规则下，
# 打包分发时这份「每项目各不相同」的业务数据会被各项目部互相覆盖。
# 现在优先读当前项目目录，读不到再回退旧的全局路径（兼容已导入过登记表的老机器）。
LEGACY_REG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'supervision_registry.json')


def _project_reg_file() -> str:
    """当前项目的登记表路径。取不到项目目录时回退到旧的全局路径。"""
    try:
        from . import project_manager as _pm
        ddir = _pm.get_project_data_dir()
        if ddir:
            return os.path.join(ddir, 'supervision_registry.json')
    except Exception:  # noqa: BLE001
        pass
    return LEGACY_REG_FILE


def _reg_file() -> str:
    """实际使用的登记表路径：项目内有就用项目的，没有才用旧的全局文件。"""
    p = _project_reg_file()
    if os.path.exists(p):
        return p
    if os.path.exists(LEGACY_REG_FILE) and p != LEGACY_REG_FILE:
        return LEGACY_REG_FILE
    return p


# 兼容旧引用（模块级常量）。注意：这是「最后一次求值」的快照，
# 运行期请用 _reg_file()，否则切换项目后仍会读旧文件。
REG_DIR = os.path.dirname(_project_reg_file())
REG_FILE = _project_reg_file()

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
    path = _reg_file()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
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


# v0.1.177：登记表没有「册」列时的统一兜底名。
# 实测事故：监理给的《资料整编要求》常常只有 序号/名称/表号/分类 四列，没有「册」列。
# registry_info() 用 `or "（未标册）"` 展示成「（未标册）233 条」，
# 而 _book_items() 直接用原始值比较 —— 条目根本没有 '册' 键，任何册名都匹配不上，
# 于是界面告诉用户有一册，点「一键整卷」却永远报「没有这一册」，还白跑一百多秒。
UNNAMED_BOOK = "（未标册）"


def _book_of(it: dict) -> str:
    """一条登记项的册名，**唯一口径**：空值一律落 UNNAMED_BOOK。

    展示（registry_info）、过滤（_book_items）、可选册列表（available_books）
    必须都走这一个函数，不能再各自写一遍兜底，否则又会分裂成两套。
    """
    return _clean_book(it.get('册')) or UNNAMED_BOOK


def _book_items(book):
    b = _clean_book(book) or UNNAMED_BOOK
    return [it for it in load_registry() if _book_of(it) == b]


def available_books() -> list:
    """登记表里实际存在的册名（按条目数从多到少）。前端下拉、错误提示都用这一个口径。"""
    items = [it for it in load_registry() if isinstance(it, dict)]
    cnt = {}
    for it in items:
        b = _book_of(it)
        cnt[b] = cnt.get(b, 0) + 1
    return [b for b, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))]


def _resolve_book(book, project_id=None):
    """把传入的册名收敛成登记表里真实存在的那一册。

    - 传了且能对上 -> 原样返回该册名（字符串）
    - 没传 -> 登记表只有一册就直接用；多册则**不猜**，返回错误字典让用户选
    - 传了但对不上 -> 返回错误字典，并附上 available_books
    返回字典即表示「不能继续」，调用方直接把它当结果返回。
    """
    have = available_books()
    b = _clean_book(book)
    if b and b in have:
        return b
    if not b:
        if len(have) == 1:
            return have[0]
        if not have:
            return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                    'todo_fields': [],
                    'error': '整编要求登记表不存在或为空，无法整卷',
                    'missing_registry': _reg_file(),
                    'hint': '请先把整编要求登记表导入到当前项目（字段：册/序号/名称/表号/分类/阶段）'}
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [], 'multi_book': True,
                'error': f'登记表里有 {len(have)} 册（{"、".join(have[:6])}），请先指定要整哪一册',
                'available_books': have,
                'hint': '在整编联动里选择册名后再点一键整卷；界面下拉已按登记表实际册名列出'}
    return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
            'todo_fields': [], 'book': b,
            'error': f'登记表里没有「{b}」这一册，现有：{"、".join(have[:6])}',
            'available_books': have,
            'hint': '按登记表实际册名重新选择；界面下拉已按登记表实际册名列出'}


def _item_category(it):
    """项 → 模板类别（映射失败返回 None）。

    v0.1.178 修了两条实测暴露的问题：

    ① **国标表名认不出**。登记表里写的是国标/行业标准的正式表名，
       比如「设备安装记录」（表号 SH/T3503-J302），而内置模板类别叫
       「设备安装检查记录」—— `_categorize` 的关键词表里只有「安装检查」，
       一个词差就把这条判成「无匹配模板」。用户在登记表里填得完全正确，
       程序却说找不到表，这不能怪用户。
       这里加一层**相似度回退**：关键词落空时，拿条目名和实际存在的模板类别名
       做比对，唯一且相似度足够高才认（多个候选一律不猜，交人工）。

    ② **B 类无模板不该算错误**。分类 B 的定义就是「生成 + 待补列清单」，
       模板没建出来属于「等人补」的正常状态；把它记进 errors 会让
       「一键整卷」的失败数和生成数一起失真。
    """
    cls = it.get('分类')
    if cls == 'DUP':
        return None
    name = (it.get('名称') or '').strip()
    if cls == 'C' or name in COLLECT_ONLY or any(k in name for k in ['监理旁站', '影像', '照片']):
        return 'C'
    cat = st._categorize(name)
    if cat != '其他':
        return cat
    return _fuzzy_category(name)


_FUZZY_MIN = 0.72
_FUZZY_CACHE = {}


def _fuzzy_category(name: str):
    """表名相似度回退（v0.1.178）。

    只在关键词匹配落空时用。规则：与实际存在的模板类别名逐一对齐，
    取 SequenceMatcher 比值最高的一个；**比值 >= 0.72 且第二名与之差距
    >= 0.06**（即"明显唯一"）才采用，否则返回 None 交人工判断。
    不采用阈值很低的模糊匹配 —— 归错表比不归更糟。
    """
    if not name:
        return None
    if not _FUZZY_CACHE:
        try:
            for c, _kws in st.CATEGORY_KEYWORDS:
                _FUZZY_CACHE[c] = None
        except Exception:  # noqa: BLE001
            return None
    import difflib
    scored = []
    for c in _FUZZY_CACHE:
        r = difflib.SequenceMatcher(None, name, c).ratio()
        scored.append((r, c))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_r, best_c = scored[0]
    second_r = scored[1][0] if len(scored) > 1 else 0.0
    if best_r >= _FUZZY_MIN and (best_r - second_r) >= 0.06:
        return best_c
    return None


def volume_status(project_id, book, workshop=''):
    """检查某册整编完成度"""
    items = _book_items(book)
    out = {'book': _clean_book(book), 'total': len(items), 'a': 0, 'b': 0, 'c': 0, 'dup': 0,
           'generated': [], 'missing': [], 'collect': [], 'dup_items': []}
    # v0.1.173：项目定位不到时不要拿空路径去 listdir，直接说明「未选项目」
    try:
        _volume_dir(project_id, book, workshop)
    except ValueError as _e:
        out.update({'ok': False, 'error': str(_e), 'missing_project': True})
        return out
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
    """项目数据根：由模板目录推导（workspace/fangong-workbench/templates_builtin → ../data/projects）

    v0.1.173：原来直接 `os.path.join(wb_root, 'projects', project_id)`，
    project_id 为空（前端没选项目、或调用方没传）时拼出来的路径是
    `.../data/projects/` —— 卷直接写进「所有项目的上一层」，不属于任何项目：
    实测整卷产物落在 `data/projects/volumes/第一册/1号车间/`，而当前项目目录下
    一个文件都没有，用户在自己的项目里找不到刚生成的卷。

    这里改成：project_id 为空时先取「当前项目」；仍取不到就抛 ValueError，
    由上层返回明确错误，而不是静默写到一个谁都不认识的地方。
    """
    pid = (project_id or '').strip()
    if not pid:
        try:
            from . import project_manager as _pm
            cur = _pm.get_current_project()
            if cur:
                pid = cur.get('id') or cur.get('project_id') or ''
        except Exception:  # noqa: BLE001
            pid = ''
    if not pid:
        raise ValueError('未指定项目：整卷必须归属到某个项目，请先选择或创建项目')
    return os.path.join(wb_root_projects(), pid)


def wb_root_projects():
    """所有项目目录的父目录（.../data/projects）。"""
    return os.path.join(os.path.dirname(st._te.TEMPLATES_DIR), 'projects')


def _volume_dir(project_id, book, workshop):
    vol = os.path.join(_proj_root(project_id), 'volumes', _clean_book(book), workshop or '全厂')
    return vol


def _project_workshops(project_id) -> list:
    """本项目实际有设备的车间列表（v0.1.178）。"""
    out = []
    try:
        from . import project_manager as _pm
        idx_path = os.path.join(_pm.get_project_data_dir(project_id), "index.json")
        if os.path.isfile(idx_path):
            with open(idx_path, "r", encoding="utf-8") as f:
                _idx = json.load(f)
            for _d in (_idx.get("devices") or {}).values():
                _ws = (_d.get("workshop") or "").strip()
                if _ws and _ws not in out:
                    out.append(_ws)
    except Exception:  # noqa: BLE001
        pass
    return sorted(out)


FACTORY_LEVEL = ('', '全厂', '全部', '各车间', '所有车间')

# v0.1.179：整卷并发出卷的车间并发度。每个车间都会起 LibreOffice 渲染页数，
# 并发太高会抢内存；3 路是实测提速明显、机器还不至于卡死的取值。
_VOLUME_WORKERS = int(os.environ.get("FANGONG_VOLUME_WORKERS", "3"))


def _resolve_workshop(workshop, project_id) -> dict:
    """把传入的车间名收敛成"设备台账里真实有设备的那个车间"。

    v0.1.179：实测事故（紫金选矿厂真实台账 248 行 / 19 个车间）。
    界面上「车间」有两个互不相通的来源：
      - /api/workshops  → 从文件名/资料文本推出来的「选矿厂」（只有一个）
      - 设备台账的「车间」列 → 粗碎站、磨浮车间、脱水车间… 共 19 个
    用户点「一键整卷」，车间框里默认填的就是「选矿厂」，于是 19 个车间的
    228 台设备一台都查不到，每条登记项都被空壳闸门拦下，生成=0、错=2，
    还提示「请先上传设备台账并确认设备已归到该车间」——台账明明已经传了。

    返回：
      {'workshop': '某车间'}          → 直接用这个车间
      {'workshop': '', 'split': True} → 按项目全部真实车间逐个出卷
      {'ok': False, ...}              → 无法判定，交回调用方报错（绝不瞎猜）
    """
    dev_ws = _project_workshops(project_id)
    w = (workshop or '').strip()
    # ① 没给 / 显式要求全厂 → 按真实车间分卷（只有一个车间就直接用它）
    if w in FACTORY_LEVEL:
        if len(dev_ws) <= 1:
            return {'workshop': dev_ws[0] if dev_ws else '全厂', 'split': False}
        return {'workshop': '', 'split': True, 'workshops': dev_ws}
    # ② 给了，且台账里真有这个车间 → 原样用
    if w in dev_ws:
        return {'workshop': w, 'split': False}
    # ③ 给了但对不上：项目还一台设备都没有 → 保持原值，让下游如实报「没设备」
    if not dev_ws:
        return {'workshop': w, 'split': False}
    # ④ 对不上，但台账里有车间：只有一个就直接用它（唯一候选，不需要问）
    if len(dev_ws) == 1:
        return {'workshop': dev_ws[0], 'split': False,
                'resolved_from': w, 'note': f'台账里只有「{dev_ws[0]}」一个车间，按它整卷'}
    # ⑤ 多个车间却填了一个不存在的名字：**按全部真实车间分卷**，并把原因带回去。
    #    这里不回错误——整卷本来就是全厂批量动作，19 个车间逐个出卷正是它该做的事；
    #    返回错误只会让用户对着一个根本不存在的车间名干瞪眼。
    return {'workshop': '', 'split': True, 'workshops': dev_ws,
            'resolved_from': w,
            'note': f'台账里没有「{w}」这个车间，改为按台账实际的 {len(dev_ws)} 个车间逐个整卷'}


def _write_boxing_list(project_id, book, results):
    """装盒清单：按「册」汇总本册下所有车间的卷目录，一册一行。

    v0.1.179 独立成函数的原因：这段要扫**整册**所有车间并渲染每个文件算页数，
    放在每个车间的 generate_volume 里等于把全册重复算 19 遍
    （实测 680 次页数调用 / 整卷 300s+）。现在只在整卷末尾算一次。
    """
    from . import volume_catalog as _vc
    _book_dir = os.path.join(_proj_root(project_id), 'volumes', _clean_book(book))
    _vols = []
    if os.path.isdir(_book_dir):
        for _ws_name in sorted(os.listdir(_book_dir)):
            _d = os.path.join(_book_dir, _ws_name)
            if not os.path.isdir(_d):
                continue
            _files = _vc.collect_volume_files(_d)
            _pages = 0
            _allcounted = True
            # v0.1.179：并发算页数（装盒清单要扫整册所有车间，串行很慢）
            if _files:
                from concurrent.futures import ThreadPoolExecutor
                _paths = [_f['路径'] for _f in _files]
                with ThreadPoolExecutor(max_workers=_vc._PAGE_WORKERS) as _pool:
                    for _r in _pool.map(_vc._safe_page_count, _paths):
                        if _r['pages']:
                            _pages += _r['pages']
                        else:
                            _allcounted = False
            _vols.append({
                'book': _clean_book(book), 'workshop': _ws_name,
                'file_count': len(_files),
                'total_pages': _pages if (_files and _allcounted) else None,
                'missing_count': 0,
            })
    if not _vols:
        return {'装盒清单': '', '盒数': 0}
    _box = os.path.join(_book_dir, '_装盒清单.xlsx')
    _vc.write_boxing_list_xlsx(_vols, _box)
    return {'装盒清单': os.path.basename(_box), '盒数': len(_vols)}


def generate_volume(project_id, book, workshop='', _skip_boxing=False):
    """一键整卷：A 类全自动生成、B 类生成（待补列清单）、C 类建归集目录

    v0.1.178：**未指定车间时按项目实际车间逐个生成**。
    实测事故：用户压根没选车间就点「一键整卷」，程序默认按「全厂」找设备，
    而设备台账里设备都归在「1号车间」「2号车间」——「全厂」一台都没有，
    于是每一条都被空壳闸门拦下：「『全厂』车间没有设备数据」
    生成=0 / 错=2。用户明明已经上传了台账、设备也归好了车间，
    程序却告诉他「请先上传设备台账」——这是最伤人的一类提示。
    台账按车间分是常态，所以默认行为必须逐个真实车间出卷，而不是假设「全厂」。
    """
    # v0.1.178：**册名没传就自己认**。
    # 实测事故：界面上册名下拉是写死的 5 个值，而监理给的登记表里册名可能叫别的
    # （或干脆没有「册」列）。用户在界面上选了一个对不上的册名点「一键整卷」，
    # 程序回一句「登记表里没有『XXX』这一册」，然后就什么都不生成。
    # 登记表里只有一册时，用户根本不需要选——直接用它。
    book = _resolve_book(book, project_id)
    if isinstance(book, dict):
        return book
    items = _book_items(book)
    # v0.1.179：车间名同样「不猜、按台账实际来」（与册名同一套原则）。
    # v0.1.178 只把「全厂」当成未指定，但界面默认填的是 /api/workshops 推出来的
    # 「选矿厂」——名字看着像车间、台账里却不存在，于是 19 个车间的设备全部落空。
    _wsr = _resolve_workshop(workshop, project_id)
    if _wsr.get('ok') is False:
        return _wsr
    workshop = _wsr.get('workshop', workshop)
    if _wsr.get('split'):
        _wss = _wsr.get('workshops') or _project_workshops(project_id)
        if len(_wss) > 1:
            # 多车间：分卷生成后合并计数（每个车间一卷，目录自然分开）
            _merged = None
            # v0.1.179：各车间彼此独立，**并发出卷**。
            # 串行时 19 个车间 × (生成 + 渲页数) 实测 200s；并发 3 路后同一批降到 ~70s。
            # 每个车间写自己的卷目录、自己的 exports 文件名（带车间名），互不覆盖。
            from concurrent.futures import ThreadPoolExecutor
            _ws_results = {}
            with ThreadPoolExecutor(max_workers=_VOLUME_WORKERS) as _pool:
                _fut = {_pool.submit(generate_volume, project_id, book, _w, True): _w
                        for _w in _wss}
                for _fut_obj, _w in _fut.items():
                    try:
                        _ws_results[_w] = _fut_obj.result()
                    except Exception as _e4:  # noqa: BLE001
                        _ws_results[_w] = {
                            'ok': False, 'generated': [], 'todo': [], 'errors': [
                                {'序号': '', '名称': _w,
                                 '原因': f'该车间整卷异常：{type(_e4).__name__}: {_e4}'}],
                            'collect_dir': [], 'todo_fields': [], 'empty_shells': []}
            for _w in _wss:
                # v0.1.179：分卷时先不算装盒清单 —— 每个车间都算一遍等于
                # 19 次全册扫描 + 19 轮重复渲染（实测整卷 300s+）。合并后算一次。
                _r = _ws_results.get(_w) or {}
                if _merged is None:
                    _merged = _r
                    _merged['by_workshop'] = {_w: {
                        'generated': len(_r.get('generated') or []),
                        'errors': len(_r.get('errors') or []),
                        'todo': len(_r.get('todo') or []),
                    }}
                else:
                    for _k in ('generated', 'todo', 'errors', 'collect_dir',
                               'todo_fields', 'empty_shells'):
                        if _r.get(_k):
                            _merged.setdefault(_k, [])
                            _merged[_k] = list(_merged.get(_k) or []) + list(_r[_k])
                    _merged.setdefault('by_workshop', {})[_w] = {
                        'generated': len(_r.get('generated') or []),
                        'errors': len(_r.get('errors') or []),
                        'todo': len(_r.get('todo') or []),
                    }
            if _merged is None:
                _merged = generate_volume(project_id, book, '全厂')
            _merged['workshops'] = _wss
            _merged['multi_workshop'] = True
            if _wsr.get('note'):
                _merged['workshop_note'] = _wsr['note']
            if _wsr.get('resolved_from'):
                _merged['workshop_resolved_from'] = _wsr['resolved_from']
            _merged['ok'] = not (_merged.get('errors') or [])
            _merged['workshop_devices'] = len(st._get_workshop_devices('', project_id))
            # v0.1.179：装盒清单在这里算一次（不是每个车间各算一次）
            try:
                _box_res = _write_boxing_list(project_id, book, _merged)
                if _box_res.get('error'):
                    _merged.setdefault('catalog', {})['装盒清单错误'] = _box_res['error']
                else:
                    _merged['catalog']['装盒清单'] = _box_res['装盒清单']
                    _merged['catalog']['盒数'] = _box_res['盒数']
            except Exception as _e3:  # noqa: BLE001
                _merged.setdefault('catalog', {})['装盒清单错误'] = f'{type(_e3).__name__}: {_e3}'
            return _merged
        workshop = _wss[0] if _wss else '全厂'
    # v0.1.173：先确认能定位到项目目录。原来 project_id 为空时 `_volume_dir` 会
    # 拼出 `data/projects/volumes/...`，产物落在「所有项目的上一层」，谁也找不到。
    try:
        _vol_preview = _volume_dir(project_id, book, workshop)
    except ValueError as _e:
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [], 'error': str(_e), 'missing_project': True,
                'hint': '请在界面上先选择/创建一个项目，再点一键整卷'}
    # v0.1.167：登记表缺失时明确报错，不再返回「成功但什么都没生成」
    if not registry_ready():
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [],
                'error': '整编要求登记表不存在或为空，无法整卷',
                'missing_registry': _reg_file(),
                'hint': '请先把整编要求登记表导入到当前项目（字段：册/序号/名称/表号/分类/阶段）'}
    if not items:
        return {'ok': False, 'generated': [], 'todo': [], 'collect_dir': [], 'errors': [],
                'todo_fields': [],
                'error': f'整编要求登记表中没有「{_clean_book(book) or UNNAMED_BOOK}」这一册的条目',
                'book': _clean_book(book) or UNNAMED_BOOK,
                'available_books': sorted({_book_of(it) for it in load_registry() if isinstance(it, dict)})}
    # v0.1.172：设备台账前置校验。整卷的 A/B 类都是"按设备一行"的确认表，
    # 设备库为空时生成出来的必然是只有表头的空壳。先同步一次设备再把结果说清楚。
    _dev_info = {'devices': 0}
    try:
        from . import project_manager as _pm
        from . import equipment_merge as _em
        _ddir = _pm.get_project_data_dir(project_id)
        _dev_info = _em.sync_devices_to_index(_ddir)
    except Exception as e:  # noqa: BLE001
        _dev_info = {'devices': 0, 'error': str(e)}
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
            # v0.1.173：原来只往 collect_dir 里塞一个路径字符串，调用方无法把它
            # 映射回登记表里的「序号/名称」，只能靠解析目录名反推 —— 目录名规则一改
            # 就对不上。这里改成结构化条目（与 generated / todo 同一形状）。
            results['collect_dir'].append({
                '序号': seq, '名称': name, '目录': d, '目录名': os.path.basename(d)})
            continue
        if not cat:
            _why = '无匹配模板，需人工确认表类型'
            if cls == 'B':
                # v0.1.178：B 类本身就是「生成+待补列清单」，模板未建是正常待办，
                # 不是错误。记进 errors 会让整卷的失败数虚高。
                results['todo'].append({'序号': seq, '名称': name, '原因': _why})
            else:
                results['errors'].append({'序号': seq, '名称': name, '原因': _why})
                results['todo'].append({'序号': seq, '名称': name, '原因': _why})
            continue
        r = st.generate_batch(category=cat, workshop=workshop or '全厂', project_id=project_id)
        if not r.get('ok'):
            _reason = r.get('error') or '生成失败'
            results['errors'].append({'序号': seq, '名称': name, '原因': _reason,
                                      '空壳拦截': bool(r.get('empty_shell_blocked'))})
            results['todo'].append({'序号': seq, '名称': name, '原因': _reason})
            continue
        # v0.1.172：整卷链路同样吃「空壳闸门」——单张模板出一份文件但没接住设备，
        # 也必须记账，不能因为 generate_batch 返回 ok 就当已生成
        if r.get('uncovered_devices'):
            results.setdefault('empty_shells', []).append({
                '序号': seq, '名称': name,
                '未覆盖设备': r.get('uncovered_devices'),
                '空表类型': r.get('empty_tables', []),
            })
        if r.get('type_fallback'):
            results.setdefault('type_fallback', []).append({
                '序号': seq, '名称': name, '借用情况': r.get('type_fallback')})
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
    todo_md = _render_todo(todo_fields, results['todo'], results['errors'],
                           results.get('empty_shells', []), results.get('type_fallback', []),
                           workshop=workshop)
    todo_path = os.path.join(vol, '_待办清单.md')
    with open(todo_path, 'w', encoding='utf-8') as f:
        f.write(todo_md)
    results['todo_file'] = todo_path

    # v0.1.175：阶段③收尾 —— 卷内目录 / 案卷封面 / 卷内备考表
    # 页次用 LibreOffice 渲染出的真实页数累计，渲不出来就如实标「未计算」，
    # 不做「1 份算 1 页」的估算（页次要印在交给监理的正式目录上）。
    try:
        from . import volume_catalog as _vc
        _pkg = _vc.build_volume_package(
            vol, book=_clean_book(book), workshop=workshop or '全厂',
            org_unit=(results.get('org_unit') or ''),
            registry_items=items, count_pages=True)
        results['catalog'] = {
            '文件': [os.path.basename(v) for v in _pkg['files'].values()],
            '件数': _pkg['catalog']['file_count'],
            '页数': _pkg['catalog']['total_pages'],
            '页数依据': _pkg['catalog']['page_basis'],
            '未生成项': _pkg['catalog']['missing_count'],
        }
        # 装盒清单按「册」汇总：扫本册下所有车间的卷目录，一册一行。
        # v0.1.179：分卷时**不在每个车间里各算一次** —— 那是 19 次全册扫描 +
        # 19 轮重复渲染（实测 680 次页数调用、整卷 300s）。改为分卷合并后算一次。
        if not _skip_boxing:
            _box_res = _write_boxing_list(project_id, book, results)
            if _box_res.get('error'):
                results.setdefault('catalog', {})['装盒清单错误'] = _box_res['error']
            else:
                results['catalog']['装盒清单'] = _box_res['装盒清单']
                results['catalog']['盒数'] = _box_res['盒数']
    except Exception as _e:  # noqa: BLE001
        results['catalog_error'] = f'{type(_e).__name__}: {_e}'

    results['ok'] = not results['errors']
    results['empty_shell_count'] = len(results.get('empty_shells', []))
    results['device_source'] = _dev_info
    results['workshop_devices'] = len(st._get_workshop_devices(workshop, project_id))
    if _dev_info.get('devices', 0) == 0:
        results['warnings'] = results.get('warnings', []) + [
            '设备库为空：整卷的确认表都是按设备出一行，没有设备只会产出表头。'
            '请先上传设备台账（Excel/CSV，含位号、设备名称、规格型号、数量、车间）并重新解析。']
    return results


def _render_todo(todo_fields, todos, errors, empty_shells=None, type_fallback=None, workshop=''):
    lines = ['# 整编待办清单', '', f'生成时间：{__import__("datetime").datetime.now():%Y-%m-%d %H:%M}',
             f'车间：{workshop or "全厂"}', '']
    if empty_shells:
        # 注意用词：这些项的文件是**已经生成**的，只是车间里还有设备没被模板覆盖。
        # 原来标题写「未计入已生成」，但 generate_volume 里它们确实进了 generated，
        # 用户按标题去卷目录找不到文件会对不上账。
        lines.append('## 〇、已生成但设备未覆盖全（需补表或人工补做）')
        for t in empty_shells:
            _devs = '、'.join(f"{d.get('位号', '')} {d.get('名称', '')}".strip()
                            for d in (t.get('未覆盖设备') or [])[:10])
            lines.append(f"- {t['序号']} {t['名称']}：已出文件；另 {len(t.get('未覆盖设备') or [])} 台未覆盖（{_devs}）")
            _et = t.get('空表类型') or []
            if _et:
                lines.append(f"  该车间无此类型设备、模板内已删表：{'、'.join(_et)}")
    if type_fallback:
        lines.append('## 〇之二、借用通用表（需人工核对检查项是否适用）')
        for t in type_fallback:
            for f in (t.get('借用情况') or [])[:10]:
                lines.append(f"- {t['序号']} {t['名称']}：{f.get('设备类型')}「{f.get('设备')}」"
                             f"借用 {f.get('借用表')} 的表")
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
    if not todo_fields and not todos and not errors and not empty_shells and not type_fallback:
        lines.append('（无待办项，全部完成）')
    return '\n'.join(lines)


def export_todo(project_id, book, workshop=''):
    """导出某册待办清单"""
    # v0.1.173：项目定位不到时回明确提示，不拼空路径去读文件
    try:
        vol = _volume_dir(project_id, book, workshop)
    except ValueError as _e:
        return f'（{_e}）'
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
    # v0.1.173：项目定位不到时不能建目录（原来会建到 data/projects/volumes 下）
    try:
        _volume_dir(project_id, book, workshop)
    except ValueError as _e:
        return {"matched": False, "error": str(_e), "missing_project": True}
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
        b = _book_of(it)
        books[b] = books.get(b, 0) + 1
        if not it.get("名称") or not str(it.get("序号") or "").strip():
            incomplete += 1
    return {
        "ready": registry_ready(),
        "path": _reg_file(),
        "exists": os.path.exists(_reg_file()),
        "total": len(items),
        "books": dict(sorted(books.items(), key=lambda kv: -kv[1])),
        "available_books": available_books(),
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
    path = _reg_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 已有文件先备份，避免反复导入覆盖掉正确版本且无法回退
    if os.path.exists(path):
        try:
            import shutil
            shutil.copy2(path, path + ".bak")
        except Exception:  # noqa: BLE001
            pass
    with open(path, "w", encoding="utf-8") as f:
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
