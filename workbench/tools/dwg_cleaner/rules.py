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


def _is_protected(t, cfg):
    return any(k in t for k in cfg["protect_keywords"])


def _is_institution(t, cfg):
    return any(k in t for k in cfg["delete_keywords"].get("institution", []))


def _strip_delete_segments(t, cfg):
    """v0.1.156：在**命中保护词**的混合文本里剥离可删段（人名标签段/日期段），
    保留保护段——解决"图号：X301 审核 王五"整块 keep 导致人名漏删的问题。
    返回清洗后文本；无可删内容返回 None。
    """
    dk = cfg.get("delete_keywords", {})
    labels = sorted(dk.get("person_labels", []), key=len, reverse=True)
    new = t
    for lab in labels:
        pat = re.compile(re.escape(lab) + r"[:：\s]{0,2}[\S]{1,12}")
        new = pat.sub("", new)
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
    mode = cfg["drawing_type_mode"]
    replaced = apply_replacements(t, cfg) if mode == "replace" else t
    if _is_protected(t, cfg):
        cleaned = _strip_delete_segments(replaced, cfg)
        if cleaned and cleaned != t:
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
