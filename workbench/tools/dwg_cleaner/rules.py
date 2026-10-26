# -*- coding: utf-8 -*-
"""规则配置加载与文字匹配。

纯逻辑模块，不依赖 AutoCAD / 任何第三方库，可独立单元测试。

判定结果 action 取值：
- "keep"    : 保留（未命中删除规则，或命中保护规则）
- "delete"  : 删除整个文字实体
- "replace" : 修改文字内容（如"施工图"→"竣工图"）

F-03（2026-10-26）：所有"判定"都基于 strip_mtext_codes() 剥离内联格式码后的
**可见文字**；但 replace 写回时保留原始 MText 格式码（仅替换连续中文词）。
"""

import json
import os
import re

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config(path=None):
    """加载规则配置。path 为空时使用包内默认 config.json。"""
    cfg_path = path or DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return normalize_config(cfg)


def normalize_config(cfg):
    """补齐默认值并预编译正则，返回可直接使用的配置字典。"""
    cfg.setdefault("protect_keywords", [])
    cfg.setdefault("replace_rules", {})
    cfg.setdefault("drawing_type_mode", "replace")

    dk = cfg.setdefault("delete_keywords", {})
    dk.setdefault("cert_labels", [])
    labels = list(dk.get("person_labels", []))
    # 长标签优先（如"专业负责人"先于"专业"），避免前缀误吞
    labels.sort(key=len, reverse=True)
    cfg["_person_label_re"] = re.compile(
        r"^(?:%s)(?:[:：\s]{1,3}[\S]{1,12})?$" % "|".join(re.escape(x) for x in labels)
    )
    # N-04：标题栏保护字段标签文字本身（"子项名称"等）在白名单模式下也保留，
    # 避免"标签被删、值被留"的残缺标题栏。精确匹配（可带冒号/尾随空白）。
    _fl = [x for x in (cfg.setdefault("titleblock", {}).get("field_labels") or []) if x]
    _fl = sorted(set(_fl), key=len, reverse=True)
    cfg["_field_label_re"] = (
        re.compile(r"^(?:%s)(?:[:：\s]{0,2})?$" % "|".join(re.escape(x) for x in _fl))
        if _fl else None
    )
    cfg["_date_re"] = [re.compile(p) for p in dk.get("date_patterns", [])]
    cfg.setdefault("titleblock", {})
    cfg.setdefault("frame_detect", {})
    cfg.setdefault("plot", {})
    return cfg


def apply_replacements(text, cfg):
    """按 replace_rules 做子串替换（如"施工图"→"竣工图"）。长词优先，避免"设计施工图"先被"施工图"吞掉。"""
    new = text
    rules_ = sorted(cfg.get("replace_rules", {}).items(), key=lambda kv: len(kv[0]), reverse=True)
    for old, repl in rules_:
        if old in new:
            new = new.replace(old, repl)
    return new


def _norm_spaces(s):
    """归一化空白：全角空格(U+3000)、制表符、普通空格全部去掉，仅用于**标签识别**。

    C2 修复：标题栏格内标签常写成"图  号""工 程 名 称"（CAD 里字间距常用空格
    撑开），精确子串匹配会漏判为非保护词而被删。归一化只用于判定，不改动原文。
    """
    return re.sub(r"[\s　]+", "", s or "")


# MText 格式码：\T1.5; \Q10; \H3.5x; \f宋体; \P(换行) \L \l 等，以及包裹大括号。
# F-03：实体原文常是 {\Q10;\T1.5;2024\Q0;年\Q10;07\Q0;月 }，格式码穿插在文字中，
# 日期/人名/证书正则要求整条完整匹配会失效。判定前先剥成可见文字，写回仍用原文。
_MTEXT_CODE_RE = re.compile(
    r"\\[A-Za-z]+[0-9.]*;?"        # \T1.5; \Q10; \H3.5; 等（带分号/数字）
    r"|\\[A-Za-z]+\b"              # \P \L \l 等无分号控制符
    r"|[{}]"                       # 包裹大括号
)


def strip_mtext_codes(s):
    """剥离 MText 内联格式码，只保留可见文字（用于判定，不用于写回）。

    例：'{\\Q10;\\T1.5;2024\\Q0;年\\Q10;07\\Q0;月 }' -> '2024年07月'
    """
    if not s:
        return ""
    return _MTEXT_CODE_RE.sub("", s)


def _visible(s):
    """供判定使用的标准化文本：先剥 MText 格式码，再去首尾空白（C2+F-03）。"""
    return strip_mtext_codes(s or "").strip()


def _is_date_text(t, cfg):
    """判断是否为日期类文本（F-03：入参先剥 MText 格式码）。

    2026-10-25 整改：date_labels 前缀**循环剥离**——"出图日期：2025.4.14"
    需先剥"日期"再剥"出图"（或反序），直到无变化再匹配日期格式。
    不带标签 → 要求整条文本完全匹配日期格式（避免误删图号等含数字串的文本）。
    """
    t = strip_mtext_codes(t or "")
    dk = cfg["delete_keywords"]
    date_labels = dk.get("date_labels", ["日期", "时间", "出图"])
    if any(k in t for k in date_labels):
        rest = t
        for _ in range(3):  # 循环剥离，处理"出图日期："等多标签叠加
            changed = False
            for k in date_labels:
                if k in rest:
                    rest = rest.replace(k, "")
                    changed = True
            if not changed:
                break
        rest = rest.strip(" ：:.")
        for re_ in cfg["_date_re"]:
            m = re_.match(rest)
            if m and m.end() == len(rest):
                return True
        return False
    for re_ in cfg["_date_re"]:
        m = re_.match(t)
        if m and m.end() == len(t):
            return True
    return False


def _is_protected(t, cfg):
    """是否命中保护词。C2：空白归一化；F-03：先剥 MText 格式码。"""
    nt = _norm_spaces(strip_mtext_codes(t))
    return any(_norm_spaces(k) in nt for k in cfg["protect_keywords"])


# N-04：工程名称类**值**（纯值不含保护词，但明显是工程/项目描述的长文本）。
# 真机：图2 标题栏「刚果（金）Manono锂矿5Mt/年采选冶项目」是"工程名称"的值，
# 但标题栏内无"工程名称"标签可关联（标签缺失），被"设计证书编号"标签的删除
# 关联当右侧值误删。判定：可见文本长度≥6 且含工程特征词（项目/工程/锂矿/采选/
# 冶炼/矿山/Manono 等）。坐标/图号/人名/标签短词均不命中。
_PROJECT_NAME_WORDS = ("项目", "工程", "锂矿", "采选", "选冶", "冶炼", "选矿",
                       "矿山", "矿厂", "Manono", "manono", "生产线", "厂房")


def _is_project_name_like(t, cfg):
    """N-04：是否为工程名称类长文本值（须保护，不得被删除关联/白名单误删）。

    排除：坐标标注、设计院/公司名（"紫金(厦门)工程设计有限公司"含"工程"但属
    institution，必须删除优先）。
    """
    s = strip_mtext_codes(t or "").strip()
    if len(s) < 6:
        return False
    if _is_axis_coordinate(s):
        return False
    if _is_institution(s, cfg):
        return False
    if any(k in s for k in _PROJECT_NAME_WORDS):
        return True
    return False


def _is_field_label(t, cfg):
    """N-04：是否命中标题栏保护字段**标签**文字（工程名称/子项名称/图号…）。

    白名单模式下标签文字本身也保留（竣工图标题栏字段标签不缺失）；值由 C1
    几何关联保护。精确匹配（可带冒号/尾随空白），避免把"值"当标签。
    """
    t = strip_mtext_codes(t or "").strip()
    if not t:
        return False
    re_ = cfg.get("_field_label_re")
    if not re_:
        return False
    return bool(re_.match(t))


# 坐标网格轴标注：X/Y 后紧跟 3 位以上数字（如 X9193900、Y549350、x:12345），
# 或纯测量数值。条带黑名单模式下作为显式保险，绝不误删图纸坐标内容（C3）。
_AXIS_COORD_RE = re.compile(r"^[XYxy][\s:：.．-]*\d{3,}(?:[.,;:：\s]*\d{0,4})*$")
_PURE_NUMBER_RE = re.compile(r"^[\d\s.,;:：．°′″'\"+\-]+$")


def _is_axis_coordinate(t):
    """C3：识别坐标网格/测量数值类标注（条带区的坐标数字不得当垃圾删除）。"""
    s = strip_mtext_codes(t or "").strip()
    if not s:
        return False
    if _AXIS_COORD_RE.match(s):
        return True
    # 纯数字/测量串（长度足够，排除孤立编号），如 "630"、"1234.567"
    if len(s) >= 3 and _PURE_NUMBER_RE.match(s) and re.search(r"\d", s):
        return True
    return False


# F-08：资质/设计证书编号值。如 A135036965（1 个字母 + 9 位连续数字），
# 也有纯 9~15 位数字的资质编号。X/Y 开头的是坐标网格，一律排除（交给 C3）。
_CERT_NUM_ALPHA_RE = re.compile(r"^[A-Za-z]\d{8,15}$")
_CERT_NUM_PURE_RE = re.compile(r"^\d{9,15}$")


def is_cert_number(t):
    """F-08：识别设计/资质证书编号串（连续、无分隔符）。图号含连字符/多段不匹配。"""
    s = strip_mtext_codes(t or "").strip().replace(" ", "")
    if not s:
        return False
    if re.match(r"^[XYxy]", s):   # 坐标 X9193900 / Y549350 优先按坐标保护
        return False
    if _CERT_NUM_ALPHA_RE.match(s) or _CERT_NUM_PURE_RE.match(s):
        return True
    return False


def _is_institution(t, cfg):
    s = strip_mtext_codes(t or "")
    return any(k in s for k in cfg["delete_keywords"].get("institution", []))


def _strip_delete_segments(t, cfg):
    """v0.1.156：在**命中保护词**的混合文本里剥离可删段（人名标签段/日期段），
    保留保护段——解决"图号：X301 审核 王五"整块 keep 导致人名漏删的问题。
    返回清洗后文本；无可删内容返回 None。
    """
    dk = cfg.get("delete_keywords", {})
    labels = sorted(dk.get("person_labels", []), key=len, reverse=True)
    prot = [k for k in (cfg.get("protect_keywords") or []) if k]
    new = t
    for lab in labels:
        pat = re.compile(re.escape(lab) + r"[:：\s]{0,2}[\S]{1,12}")

        def _sub_guard(m, _prot=prot):
            """2026-10-26 修复：人名标签会误伤含保护词的合法字段。

            例：标签「设计」+ 保护词「设计阶段」→ 原文 '{\\T1.5;设计阶段}'
            被剥成 '{\\T1.5'（MText 格式码残缺，标题栏内容损坏）。
            命中保护词的匹配段一律不剥；C2：判定时同样做空白归一化，
            使"图  号"这类带字间距的标签也能被保护。
            """
            seg = m.group(0)
            nseg = _norm_spaces(seg)
            if any(_norm_spaces(k) in nseg for k in _prot):
                return seg
            return ""

        new = pat.sub(_sub_guard, new)
    # 日期段剥离：兼容任意位置（含"日期：2025.4.14"标签+串）；
    # 收紧规则防误伤图号（4 位年开头 + 前后非字母数字，如 "X2025-01" 不剥）
    for lab in dk.get("date_labels", ["日期", "时间", "出图"]):
        new = re.sub(re.escape(lab) + r"[:：\s]{0,2}", " ", new)
    date_pat = re.compile(
        r"(?<![A-Za-z0-9])\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]?\s*\d{0,2}\s*日?(?![0-9])"
        r"|(?<![A-Za-z0-9])[〇零一二三四五六七八九]{4}\s*年\s*[一二三四五六七八九十]{1,3}\s*月(?![0-9])")
    new = date_pat.sub("", new)
    new = re.sub(r"[ ：:；;，,]{2,}", " ", new).strip(" ：:；;，,.-")
    if not new:
        return None  # 全删光了 → 保持保护词语义，不整块删
    return new if new != t else None


def judge_whitelist_text(text, cfg):
    """标题栏区域白名单判定（真实标题栏矩形）：

    凡位于标题栏区域内的文字，不命中 protect_keywords（工程名称/图纸名称/图号/
    比例等）的一律删除——可真正删掉"旁边的人名"、任意格式的公司名、日期、
    证书编号等黑名单规则覆盖不到的信息。

    F-03：判定基于剥离 MText 格式码后的可见文字；"施工图→竣工图"替换写回保留
    原文格式码（连续中文词不被格式码打断）。
    返回 (action, reason, new_text)，与 judge_text 同构。
    """
    raw = text or ""
    t = _visible(raw)
    if not t:
        return "keep", "empty", None
    # C3：坐标网格/测量数值即使落入标题栏区域也保留（防区域外扩误删坐标）
    if _is_axis_coordinate(t):
        return "keep", "axis_coordinate", None
    # N-04：标题栏保护字段标签文字本身（工程名称/子项名称/图号…）保留，
    # 避免"子项名称"这类标签被白名单整删、只剩值（残缺标题栏）。
    if _is_field_label(t, cfg):
        return "keep", "field_label", None
    # N-04：工程名称类**值**（长文本含项目/工程/锂矿等特征词）保留。
    # 真机图2 标题栏无"工程名称"标签可关联，此值只能靠内容规则保护。
    if _is_project_name_like(t, cfg):
        return "keep", "project_name", None
    # F-08：资质/设计证书编号（A135036965）即使在区域外被证书扩展捞到也删
    if is_cert_number(t):
        return "delete", "cert_number", None
    mode = cfg["drawing_type_mode"]
    raw_repl = apply_replacements(raw, cfg) if mode == "replace" else raw   # 写回（保留格式码）
    t_repl = apply_replacements(t, cfg) if mode == "replace" else t         # 判定
    if _is_protected(t, cfg):
        cleaned = _strip_delete_segments(t_repl, cfg)
        # C2：仅空白差异（如标签"图  号"被压成"图 号"）不算实质修改，保留原文
        if cleaned and _norm_spaces(cleaned) != _norm_spaces(t):
            return "replace", "mixed_cleaned", cleaned
        if raw_repl != raw:
            return "replace", "replaced_in_protected", raw_repl
        return "keep", "protected", None
    if raw_repl != raw:
        return "replace", "replaced", raw_repl
    return "delete", "whitelist_non_protected", None


def judge_text(text, cfg):
    """对单条文字内容做判定（条带/页眉黑名单模式），返回 (action, reason, new_text)。

    F-03：判定基于剥离 MText 格式码后的可见文字；替换写回保留原文格式码。
    - delete: reason 为命中类别
    - replace: new_text 为替换后的完整文本
    - keep: new_text 为 None
    """
    raw = text or ""
    t = _visible(raw)
    if not t:
        return "keep", "empty", None

    mode = cfg["drawing_type_mode"]
    # delete 模式下不做"施工图→竣工图"替换，直接按删除处理
    raw_repl = apply_replacements(raw, cfg) if mode == "replace" else raw
    t_repl = apply_replacements(t, cfg) if mode == "replace" else t

    # 保护字段：只允许替换，不允许删除（安全优先，命中情况写日志人工复核）
    if _is_protected(t, cfg):
        if raw_repl != raw:
            return "replace", "replaced_in_protected", raw_repl
        return "keep", "protected", None

    # C3：坐标网格/测量数值在任何模式下都保留（条带回退区的坐标标注不得误删）
    if _is_axis_coordinate(t):
        return "keep", "axis_coordinate", None

    # F-08：资质/设计证书编号（A135036965 等）任何模式都删（已排除 X/Y 坐标）
    if is_cert_number(t):
        return "delete", "cert_number", None

    # 删除判定（基于剥离后的可见文本）
    if _is_institution(t_repl, cfg):
        return "delete", "institution", None
    if cfg["_person_label_re"].match(t_repl):
        return "delete", "person_label", None
    if _is_date_text(t_repl, cfg):
        return "delete", "date", None
    dk = cfg["delete_keywords"]
    if mode == "delete" and any(k in t_repl for k in dk.get("drawing_type", [])):
        return "delete", "drawing_type", None

    if raw_repl != raw:
        return "replace", "replaced", raw_repl
    return "keep", "no_match", None
