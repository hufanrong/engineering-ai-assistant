# -*- coding: utf-8 -*-
"""规则配置加载与文字匹配。

纯逻辑模块，不依赖 AutoCAD / 任何第三方库，可独立单元测试。

判定结果 action 取值：
- "keep"    : 保留（未命中删除规则，或命中保护规则）
- "delete"  : 删除整个文字实体
- "replace" : 修改文字内容（如"施工图"→"竣工图"）
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
    labels = list(dk.get("person_labels", []))
    # 长标签优先（如"专业负责人"先于"专业"），避免前缀误吞
    labels.sort(key=len, reverse=True)
    cfg["_person_label_re"] = re.compile(
        r"^(?:%s)(?:[:：\s]{1,3}[\S]{1,12})?$" % "|".join(re.escape(x) for x in labels)
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


def _is_date_text(t, cfg):
    """判断是否为日期类文本。

    2026-10-25 整改：date_labels 前缀**循环剥离**——"出图日期：2025.4.14"
    需先剥"日期"再剥"出图"（或反序），直到无变化再匹配日期格式。
    不带标签 → 要求整条文本完全匹配日期格式（避免误删图号等含数字串的文本）。
    """
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


def _norm_spaces(s):
    """归一化空白：全角空格(U+3000)、制表符、普通空格全部去掉，仅用于**标签识别**。

    C2 修复：标题栏格内标签常写成"图  号""工 程 名 称"（CAD 里字间距常用空格
    撑开），精确子串匹配会漏判为非保护词而被删。归一化只用于判定，不改动原文。
    """
    return re.sub(r"[\s\u3000]+", "", s or "")


def _is_protected(t, cfg):
    """是否命中保护词。C2：比对前对正文与关键词都做空白归一化。"""
    nt = _norm_spaces(t)
    return any(_norm_spaces(k) in nt for k in cfg["protect_keywords"])


# 坐标网格轴标注：X/Y 后紧跟 3 位以上数字（如 X9193900、Y549350、x:12345），
# 或纯测量数值。条带黑名单模式下作为显式保险，绝不误删图纸坐标内容（C3）。
_AXIS_COORD_RE = re.compile(r"^[XYxy][\s:：.．-]*\d{3,}(?:[.,;:：\s]*\d{0,4})*$")
_PURE_NUMBER_RE = re.compile(r"^[\d\s.,;:：．°′″'\"+\-]+$")


def _is_axis_coordinate(t):
    """C3：识别坐标网格/测量数值类标注（条带区的坐标数字不得当垃圾删除）。"""
    s = (t or "").strip()
    if not s:
        return False
    if _AXIS_COORD_RE.match(s):
        return True
    # 纯数字/测量串（长度足够，排除孤立编号），如 "630"、"1234.567"
    if len(s) >= 3 and _PURE_NUMBER_RE.match(s) and re.search(r"\d", s):
        return True
    return False


def _is_institution(t, cfg):
    return any(k in t for k in cfg["delete_keywords"].get("institution", []))


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
    """标题栏区域白名单判定（2026-10-25 整改，重点方案）：

    凡位于标题栏区域内的文字，不命中 protect_keywords（工程名称/图纸名称/图号/
    比例等）的一律删除——可真正删掉"旁边的人名"、任意格式的公司名、日期、
    证书编号等黑名单规则覆盖不到的信息。

    v0.1.156 增强：命中保护词的混合文本（"图号：X301 审核 王五"）做局部清洗，
    剥离人名标签段与日期段后保留保护段。

    返回 (action, reason, new_text)，与 judge_text 同构。
    """
    t = (text or "").strip()
    if not t:
        return "keep", "empty", None
    # C3：坐标网格/测量数值即使落入标题栏区域也保留（防区域外扩误删坐标）
    if _is_axis_coordinate(t):
        return "keep", "axis_coordinate", None
    mode = cfg["drawing_type_mode"]
    replaced = apply_replacements(t, cfg) if mode == "replace" else t
    if _is_protected(t, cfg):
        cleaned = _strip_delete_segments(replaced, cfg)
        # C2：仅空白差异（如标签"图  号"被压成"图 号"）不算实质修改，保留原文
        if cleaned and _norm_spaces(cleaned) != _norm_spaces(t):
            return "replace", "mixed_cleaned", cleaned
        if replaced != t:
            return "replace", "replaced_in_protected", replaced
        return "keep", "protected", None
    if replaced != t:
        return "replace", "replaced", replaced
    return "delete", "whitelist_non_protected", None


def judge_text(text, cfg):
    """对单条文字内容做判定，返回 (action, reason, new_text)。

    - delete: reason 为命中类别
    - replace: new_text 为替换后的完整文本
    - keep: new_text 为 None
    """
    t = (text or "").strip()
    if not t:
        return "keep", "empty", None

    mode = cfg["drawing_type_mode"]
    # delete 模式下不做"施工图→竣工图"替换，直接按删除处理
    replaced = apply_replacements(t, cfg) if mode == "replace" else t

    # 保护字段：只允许替换，不允许删除（安全优先，命中情况写日志人工复核）
    if _is_protected(t, cfg):
        if replaced != t:
            return "replace", "replaced_in_protected", replaced
        return "keep", "protected", None

    # C3：坐标网格/测量数值在任何模式下都保留（条带回退区的坐标标注不得误删）
    if _is_axis_coordinate(t):
        return "keep", "axis_coordinate", None

    # 删除判定（基于替换后的文本，施工图字样已处理）
    if _is_institution(replaced, cfg):
        return "delete", "institution", None
    if cfg["_person_label_re"].match(replaced):
        return "delete", "person_label", None
    if _is_date_text(replaced, cfg):
        return "delete", "date", None
    dk = cfg["delete_keywords"]
    if mode == "delete" and any(k in replaced for k in dk.get("drawing_type", [])):
        return "delete", "drawing_type", None

    if replaced != t:
        return "replace", "replaced", replaced
    return "keep", "no_match", None
