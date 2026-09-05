# 繁工AI 本地解析工作台 - 标准核验适配器（v0.1.15）
# 目的：确保平台库中的规范"使用时是现行有效"，且能在标准废止时给出最新版号。
#
# 核验通道（按优先级依次尝试）：
#   1) config.PLATFORM_SEARCH_ENDPOINT（自定义核验服务/内网 Agent 端点）
#      POST {"std_no": "GB 50231-2009"} → {"std_no":..., "status": "现行|废止|未知", "latest_no": "GB 50231-2026"}
#   2) 全国标准信息公共服务平台 openstd.samr.gov.cn（尽力而为，可配置开关）
#   3) 全部不可用 → {"status": "unknown"}（由人工核验，不阻断使用）
#
# 注意：标准全文/最新版文件无法自动下载（版权与无稳定公开下载源），
#       核验发现废止时给出最新版号并提示人工上传替换，符合"确保使用时可调用规范内容"。

import os
import re
import json

import requests

from . import config

_OPENSTD_BASE = "https://openstd.samr.gov.cn/bzgk/gb/"
_TIMEOUT = 12


def _normalize_no(std_no: str) -> str:
    """'GB/T50430-2017' / 'GB 50231-2009' → 统一大写无空格 'GB/T 50430-2017' 形式（尽力标准化）。"""
    s = (std_no or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    m = re.match(r"^(GB/?T|GB|JGJ|HG/T|DL/T|JB/T|SH/T|SY/T|NB/T|CJ/T|TSG|AQ|ISO|EN|DIN|ASTM|API|ASME|IEC)\s*[/]?\s*T?\s*(\d+)[-—:]?(\d{4})?$", s)
    if m:
        prefix, num, year = m.group(1), m.group(2), m.group(3) or ""
        p = prefix.upper().replace(" ", "")
        if p.startswith("GB") and "T" in p:
            p = "GB/T"
        elif p.startswith("GB"):
            p = "GB"
        return f"{p} {num}" + (f"-{year}" if year else "")
    return s


def _query_openstd(std_no: str):
    """全国标准信息公共服务平台检索（尽力而为）。返回 (status, latest_no) 或 None。"""
    if not config.STD_VERIFY_OPENSTD:
        return None
    no = _normalize_no(std_no)
    # 尝试多种查询格式
    candidates = [no, no.replace(" ", ""), no.split("-")[0].replace(" ", "")]
    for q in candidates:
        try:
            url = _OPENSTD_BASE + "std_list?p.p1=0&p.p90=circulation_date&p.p91=desc&p.p2=" + requests.utils.quote(q)
            r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            text = r.text
            m = re.search(r"共\s*(?:&nbsp;)?\s*(\d+)\s*(?:&nbsp;)?\s*条标准", text)
            if not m or m.group(1) == "0":
                continue
            # 解析表格行：标准号 / 名称 / 状态 / 实施日期
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)
            for row in rows[:30]:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                clean = [re.sub(r"<[^>]+>|\s+", " ", c).strip() for c in cells]
                if not clean or len(clean) < 3:
                    continue
                row_no = clean[0]
                if no.split("-")[0].replace(" ", "") not in row_no.replace(" ", ""):
                    continue
                status = "未知"
                hay = " ".join(clean)
                if "废止" in hay or "代替" in hay or "作废" in hay:
                    status = "废止"
                elif "现行" in hay or "实施" in hay or "有效" in hay:
                    status = "现行"
                latest = None
                mm = re.search(r"代替[:：]?\s*([A-Za-z0-9/ .\-]+)", hay)
                if mm:
                    latest = mm.group(1).strip()
                return {"status": status, "latest_no": latest}
        except Exception:  # noqa: BLE001（网络/解析失败视为不可用，走下一通道）
            continue
    return None


def verify_std(std_no: str) -> dict:
    """核验单个标准。返回 {"std_no", "status": 现行|废止|未知|unknown, "latest_no", "source"}。"""
    no = _normalize_no(std_no)
    # 1) 自定义核验端点（最高优先）
    ep = (config.PLATFORM_SEARCH_ENDPOINT or "").strip().rstrip("/")
    if ep:
        try:
            r = requests.post(ep, json={"std_no": no}, timeout=_TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                st = d.get("status", "未知")
                if st in ("现行", "废止"):
                    return {"std_no": no, "status": st,
                            "latest_no": d.get("latest_no") or None,
                            "source": "endpoint"}
        except Exception:  # noqa: BLE001
            pass
    # 2) openstd 尽力而为
    r = _query_openstd(no)
    if r:
        return {"std_no": no, "status": r["status"],
                "latest_no": r.get("latest_no"), "source": "openstd"}
    # 3) 不可用
    return {"std_no": no, "status": "unknown", "latest_no": None, "source": "unavailable"}
