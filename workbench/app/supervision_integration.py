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
    if not os.path.exists(REG_FILE):
        return []
    with open(REG_FILE, encoding='utf-8') as f:
        return json.load(f)


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
    vol = _volume_dir(project_id, book, workshop)
    os.makedirs(vol, exist_ok=True)
    items = _book_items(book)
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
        dst = os.path.join(vol, f'{seq}_{re.sub(r"[\\/:*?\"<>|]", "", name)[:50]}.docx')
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
