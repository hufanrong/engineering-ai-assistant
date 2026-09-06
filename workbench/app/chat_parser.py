# 繁工AI 本地解析工作台 - 群聊天文件自动关联（v0.1.34）
# 目的：上传群聊导出文件（微信/QQ TXT、HTML、CSV），自动解析每条消息，
#       提取涉及的设备位号、车间、事项关键词，建立关联到项目图谱。
#
# 口径（用户锁定）：
#   - 我最终会上传手上所有该项目资料，包括一些群聊天文件，能建立联系的都完成关联
#   - 不能确认时留存为人工确认

import re
import os
import json
import datetime
from html.parser import HTMLParser

# 位号正则（与 field_record 一致）
_TAG_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])")
_WORKSHOP_RE = re.compile(r"(\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间")

# 微信/QQ 聊天记录时间戳模式
# 微信导出 TXT: "2024-01-15 10:30:25 张三(123456)" 或 "2024/1/15 10:30 张三"
# QQ 导出 TXT: "消息对象: 张三\n2024-01-15 10:30:25\n内容"
_WECHAT_TS_RE = re.compile(
    r"^(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)(?:\(\d+\))?\s*$"
)
_QQ_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})$")

# 事项关键词（工程现场常见讨论主题）
_TOPIC_KEYWORDS = {
    "到货/开箱": ["到货", "开箱", "拆箱", "装箱单", "发货", "物流", "快递", "送货"],
    "安装/施工": ["安装", "施工", "就位", "找正", "找平", "焊接", "管道", "法兰", "螺栓", "吊装"],
    "验收/检查": ["验收", "检查", "检验", "试压", "试运转", "调试", "报验", "隐蔽"],
    "问题/缺陷": ["问题", "缺陷", "损坏", "破损", "漏", "堵", "故障", "异常", "不对", "错了", "返工"],
    "变更/洽商": ["变更", "洽商", "修改", "改图", "设计", "签证"],
    "安全/交底": ["安全", "交底", "危险", "注意", "防护", "安全帽", "高空"],
    "进度/计划": ["进度", "计划", "工期", "明天", "后天", "下周", "加班", "赶工"],
    "资料/文档": ["资料", "文档", "表格", "记录", "签字", "盖章", "报审", "报验"],
}


def is_chat_file(path: str, text: str = "") -> bool:
    """判断文件是否为群聊导出文件。基于文件名和内容模式。"""
    name = os.path.basename(path).lower()
    # 文件名提示
    chat_name_hints = ["聊天", "chat", "群聊", "消息记录", "wechat", "qq", "微信群"]
    if any(h in name for h in chat_name_hints):
        return True
    # 内容模式：前 2000 字符中出现多条时间戳+发送人模式
    if not text:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(4000)
        except Exception:  # noqa: BLE001
            return False
    # 统计微信模式行数
    wechat_count = 0
    qq_count = 0
    for line in text.split("\n")[:100]:
        if _WECHAT_TS_RE.match(line.strip()):
            wechat_count += 1
        if _QQ_TS_RE.match(line.strip()):
            qq_count += 1
    return wechat_count >= 2 or qq_count >= 2


def parse_chat_text(text: str) -> list:
    """解析纯文本聊天记录为消息列表。
    返回 [{ts, sender, content, line_no}]。"""
    messages = []
    lines = text.split("\n")
    i = 0
    current_sender = None
    current_ts = None
    current_content = []

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        # 微信模式：时间戳 + 发送人
        m = _WECHAT_TS_RE.match(stripped)
        if m:
            # 保存上一条
            if current_sender and current_content:
                messages.append({
                    "ts": current_ts,
                    "sender": current_sender,
                    "content": "\n".join(current_content).strip(),
                })
            current_ts = m.group(1)
            current_sender = m.group(2).strip()
            current_content = []
            i += 1
            continue

        # QQ 模式：单独一行时间戳，下一行是内容
        m = _QQ_TS_RE.match(stripped)
        if m:
            if current_sender and current_content:
                messages.append({
                    "ts": current_ts,
                    "sender": current_sender,
                    "content": "\n".join(current_content).strip(),
                })
            current_ts = m.group(1)
            # QQ 格式中发送人通常在上一行 "消息对象: xxx"
            current_content = []
            i += 1
            continue

        # QQ "消息对象:" 行
        if stripped.startswith("消息对象:") or stripped.startswith("消息对象："):
            current_sender = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
            i += 1
            continue

        # 普通内容行
        if stripped and not stripped.startswith("=====") and not stripped.startswith("-----"):
            current_content.append(stripped)
        i += 1

    # 最后一条
    if current_sender and current_content:
        messages.append({
            "ts": current_ts,
            "sender": current_sender,
            "content": "\n".join(current_content).strip(),
        })

    return messages


class _ChatHTMLParser(HTMLParser):
    """简易微信 HTML 聊天记录解析器。"""
    def __init__(self):
        super().__init__()
        self.messages = []
        self._in_msg = False
        self._current = {}
        self._capture = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        if "message" in cls or "msg" in cls:
            self._in_msg = True
            self._current = {}
        if "time" in cls or "date" in cls:
            self._capture = "ts"
            self._buf = []
        if "nickname" in cls or "sender" in cls or "name" in cls:
            self._capture = "sender"
            self._buf = []
        if "content" in cls or "text" in cls:
            self._capture = "content"
            self._buf = []

    def handle_endtag(self, tag):
        if self._capture:
            val = "".join(self._buf).strip()
            if val:
                self._current[self._capture] = val
            self._capture = None
            self._buf = []
        if tag in ("div", "p", "li") and self._in_msg:
            if self._current.get("content") or self._current.get("sender"):
                self.messages.append(self._current)
                self._current = {}
                self._in_msg = False

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def parse_chat_html(html_text: str) -> list:
    """解析 HTML 格式聊天记录。"""
    parser = _ChatHTMLParser()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001
        pass
    return [m for m in parser.messages if m.get("content") or m.get("sender")]


def parse_chat_file(path: str) -> dict:
    """解析群聊文件，返回 {messages, message_count, senders, date_range}。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except Exception as e:  # noqa: BLE001
        return {"messages": [], "message_count": 0, "error": str(e)}

    if ext == ".html" or ext == ".htm":
        messages = parse_chat_html(raw)
    elif ext == ".csv":
        # CSV 格式：时间,发送人,内容
        messages = []
        import csv
        import io
        reader = csv.reader(io.StringIO(raw))
        for row in reader:
            if len(row) >= 3:
                messages.append({"ts": row[0].strip(), "sender": row[1].strip(), "content": row[2].strip()})
            elif len(row) == 2:
                messages.append({"ts": "", "sender": row[0].strip(), "content": row[1].strip()})
    else:
        messages = parse_chat_text(raw)

    senders = sorted(set(m.get("sender", "") for m in messages if m.get("sender")))
    ts_list = [m.get("ts", "") for m in messages if m.get("ts")]
    date_range = [ts_list[0], ts_list[-1]] if ts_list else []

    return {
        "messages": messages,
        "message_count": len(messages),
        "senders": senders,
        "sender_count": len(senders),
        "date_range": date_range,
    }


def extract_from_messages(messages: list) -> dict:
    """从消息列表提取位号、车间、事项。
    返回 {tags: {tag: [msg_indices]}, workshops: {ws: [msg_indices]}, topics: {topic: [msg_indices]}, tag_sender_pairs}。"""
    tags = {}
    workshops = {}
    topics = {}
    cn_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}

    for idx, msg in enumerate(messages):
        content = msg.get("content", "")
        if not content:
            continue
        # 位号
        for tag in _TAG_RE.findall(content):
            tags.setdefault(tag, []).append(idx)
        # 车间
        for m in _WORKSHOP_RE.finditer(content):
            num = cn_map.get(m.group(1), m.group(1))
            ws = f"{num}号车间"
            workshops.setdefault(ws, []).append(idx)
        # 事项
        for topic, keywords in _TOPIC_KEYWORDS.items():
            if any(kw in content for kw in keywords):
                topics.setdefault(topic, []).append(idx)

    return {
        "tags": tags,
        "workshops": workshops,
        "topics": topics,
        "tag_count": len(tags),
        "workshop_count": len(workshops),
        "topic_count": len(topics),
    }


def build_summary(messages: list, extracted: dict) -> dict:
    """生成群聊摘要：按设备/车间/事项汇总。"""
    summary = {
        "by_tag": {},
        "by_workshop": {},
        "by_topic": {},
        "active_senders": {},
        "unresolved_questions": [],
    }

    # 按位号汇总
    for tag, indices in extracted.get("tags", {}).items():
        msgs = [messages[i] for i in indices if i < len(messages)]
        summary["by_tag"][tag] = {
            "mention_count": len(indices),
            "senders": sorted(set(m.get("sender", "") for m in msgs if m.get("sender"))),
            "latest_content": msgs[-1].get("content", "")[:200] if msgs else "",
            "topics": sorted(set(
                topic for topic, t_indices in extracted.get("topics", {}).items()
                for i in t_indices if i in indices
            )),
        }

    # 按车间汇总
    for ws, indices in extracted.get("workshops", {}).items():
        msgs = [messages[i] for i in indices if i < len(messages)]
        summary["by_workshop"][ws] = {
            "mention_count": len(indices),
            "tags": sorted(set(
                tag for tag, t_indices in extracted.get("tags", {}).items()
                for i in t_indices if i in indices
            )),
            "latest_content": msgs[-1].get("content", "")[:200] if msgs else "",
        }

    # 按事项汇总
    for topic, indices in extracted.get("topics", {}).items():
        summary["by_topic"][topic] = {
            "mention_count": len(indices),
            "tags": sorted(set(
                tag for tag, t_indices in extracted.get("tags", {}).items()
                for i in t_indices if i in indices
            )),
        }

    # 活跃发送人
    sender_count = {}
    for msg in messages:
        s = msg.get("sender", "")
        if s:
            sender_count[s] = sender_count.get(s, 0) + 1
    summary["active_senders"] = dict(sorted(sender_count.items(), key=lambda x: -x[1])[:20])

    # 未解决问题（含问号且涉及设备/问题关键词的消息）
    for msg in messages:
        content = msg.get("content", "")
        if ("?" in content or "？" in content) and (_TAG_RE.search(content) or any(kw in content for kw in ["问题", "怎么", "为什么", "怎么办", "谁", "什么时候"])):
            summary["unresolved_questions"].append({
                "sender": msg.get("sender", ""),
                "ts": msg.get("ts", ""),
                "content": content[:300],
            })

    return summary


def analyze_chat(path: str) -> dict:
    """完整分析群聊文件：解析 + 提取 + 摘要。"""
    parsed = parse_chat_file(path)
    if parsed.get("error"):
        return {"ok": False, "error": parsed["error"]}
    messages = parsed["messages"]
    extracted = extract_from_messages(messages)
    summary = build_summary(messages, extracted)
    return {
        "ok": True,
        "file_name": os.path.basename(path),
        "message_count": parsed["message_count"],
        "sender_count": parsed["sender_count"],
        "senders": parsed["senders"],
        "date_range": parsed["date_range"],
        "extracted": extracted,
        "summary": summary,
        "messages_preview": messages[:50],  # 预览前50条
    }
