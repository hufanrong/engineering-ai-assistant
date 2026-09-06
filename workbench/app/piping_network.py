"""
v0.1.47：设备间管线/连接关系

功能：
1. 从CAD/PID图纸中提取管线（LINE实体）和管线编号（文字标注）
2. 识别管线介质（从管线编号或附近文字推断）
3. 通过空间 proximity 关联管线两端连接的设备
4. 建立设备-管线-设备连接网络
5. 支持从台账/文本中提取的管线信息补充

设计原则：
- 管线编号格式：如 P-101（工艺管道）、C-101（压缩空气）、S-101（蒸汽）、W-101（水）等
- 注意与设备位号区分：管线编号通常在管道旁边，设备位号在设备旁边
- 通过LINE端点附近的设备图块/位号关联连接关系
- 介质从管线编号前缀或附近文字推断
- 无法确定的连接留人工确认
"""

import os
import json
import re
import math
from . import config

PIPING_FILE = None

# 管线介质前缀映射（常见PID图例）
PIPE_MEDIUM_MAP = {
    "P": "工艺介质", "PG": "工艺气体", "PL": "工艺液体",
    "C": "压缩空气", "CA": "压缩空气", "IA": "仪表空气",
    "S": "蒸汽", "SH": "高压蒸汽", "SM": "中压蒸汽", "SL": "低压蒸汽",
    "CWS": "循环冷却水供水", "CWR": "循环冷却水回水",
    "W": "水", "FW": "消防水", "DW": "脱盐水", "BW": "锅炉给水",
    "N": "氮气", "NG": "天然气", "H": "氢气", "O": "氧气",
    "A": "氨", "AC": "酸", "AL": "碱", "OIL": "油",
    "DR": "排液", "VT": "排气", "VE": "真空",
    "HW": "热水", "LS": "低压蒸汽", "MS": "中压蒸汽", "HS": "高压蒸汽",
    "FO": "燃料油", "FG": "燃料气", "GO": "瓦斯油",
    "BD": "排污", "SD": "排净", "OF": "溢流",
}


def _ensure():
    global PIPING_FILE
    if PIPING_FILE is None:
        PIPING_FILE = os.path.join(config.DATA_DIR, "piping_network.json")


def _load() -> dict:
    _ensure()
    if os.path.exists(PIPING_FILE):
        try:
            with open(PIPING_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {"pipes": {}, "connections": [], "device_pipes": {}}


def _save(m: dict):
    _ensure()
    with open(PIPING_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


# ---------------- 管线提取 ----------------

def _is_pipe_number(text: str) -> dict:
    """判断文字是否为管线编号，返回 {is_pipe, pipe_no, medium, size}。"""
    if not text:
        return {"is_pipe": False}
    text = text.strip()
    # 管线编号格式：前缀-数字，如 P-101, CWS-101, SH-201
    # 也可能包含管径，如 P-101-DN50, P-101-50
    m = re.match(r"^([A-Z]{1,4})-(\d{2,5})(?:[-_](?:DN)?(\d{1,4}))?$", text)
    if m:
        prefix = m.group(1)
        number = m.group(2)
        size = m.group(3)
        medium = PIPE_MEDIUM_MAP.get(prefix, "未知介质")
        return {"is_pipe": True, "pipe_no": f"{prefix}-{number}",
                "medium": medium, "size": size, "prefix": prefix}
    return {"is_pipe": False}


def _distance_point_to_line(px, py, x1, y1, x2, y2):
    """点到线段的距离。"""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)


def extract_pipes_from_cad(cache: dict) -> list:
    """从CAD解析缓存中提取管线信息。
    返回 [{pipe_no, medium, size, x, y, file, source, endpoints}]
    """
    pipes = []
    if not cache:
        return pipes
    structure = cache.get("structure") or {}
    sp = structure.get("spatial") or {}
    labels = structure.get("text_labels", []) or []
    lines = sp.get("lines", []) or []
    fname = cache.get("file_name", "")

    # 1) 从文字标注中识别管线编号
    for lbl in labels[:1000]:
        text = (lbl.get("text", "") or "").strip()
        pipe_info = _is_pipe_number(text)
        if pipe_info["is_pipe"]:
            # 查找附近的线段（管线）
            px, py = lbl.get("x"), lbl.get("y")
            nearest_line = None
            nearest_dist = float("inf")
            for line in lines[:500]:
                if len(line) >= 4:
                    dist = _distance_point_to_line(px, py, line[0], line[1], line[2], line[3])
                    if dist < 200 and dist < nearest_dist:
                        nearest_dist = dist
                        nearest_line = line
            pipe_entry = {
                "pipe_no": pipe_info["pipe_no"],
                "medium": pipe_info["medium"],
                "size": pipe_info.get("size"),
                "x": px, "y": py,
                "file": fname,
                "source": "cad_label",
                "confidence": 0.8 if nearest_line else 0.5,
            }
            if nearest_line:
                pipe_entry["line"] = list(nearest_line)
                pipe_entry["endpoints"] = [
                    {"x": nearest_line[0], "y": nearest_line[1]},
                    {"x": nearest_line[2], "y": nearest_line[3]},
                ]
            pipes.append(pipe_entry)

    return pipes


def extract_devices_from_cad(cache: dict) -> list:
    """从CAD解析缓存中提取设备（带坐标）。"""
    devices = []
    if not cache:
        return devices
    structure = cache.get("structure") or {}
    sp = structure.get("spatial") or {}
    labels = structure.get("text_labels", []) or []
    fname = cache.get("file_name", "")

    # 从图块属性提取
    for b in sp.get("blocks", [])[:500]:
        attrs = {a.get("tag", ""): a.get("value", "") for a in b.get("attrs", [])}
        tag = attrs.get("位号") or attrs.get("设备位号") or attrs.get("TAG")
        if tag:
            devices.append({
                "tag": tag, "x": b.get("x"), "y": b.get("y"),
                "file": fname, "source": "cad_block",
            })

    # 从文字标注提取（位号格式）
    for lbl in labels[:500]:
        text = (lbl.get("text", "") or "").strip()
        m = re.match(r"^[A-Z]{1,4}-?\d{2,4}[A-Z]?$", text)
        if m and not _is_pipe_number(text)["is_pipe"]:
            devices.append({
                "tag": text, "x": lbl.get("x"), "y": lbl.get("y"),
                "file": fname, "source": "cad_label",
            })

    return devices


# ---------------- 连接网络构建 ----------------

def build_connections(pipes: list, devices: list, proximity_threshold: float = 500) -> list:
    """构建设备-管线-设备连接关系。
    通过管线端点附近的设备关联连接。
    """
    connections = []
    for pipe in pipes:
        endpoints = pipe.get("endpoints") or []
        if not endpoints or len(endpoints) < 2:
            continue

        connected_devices = []
        for ep in endpoints:
            nearest_device = None
            nearest_dist = float("inf")
            for dev in devices:
                if dev.get("x") is None or dev.get("y") is None:
                    continue
                dist = math.sqrt((dev["x"] - ep["x"]) ** 2 + (dev["y"] - ep["y"]) ** 2)
                if dist < proximity_threshold and dist < nearest_dist:
                    nearest_dist = dist
                    nearest_device = dev
            if nearest_device:
                connected_devices.append({
                    "device": nearest_device["tag"],
                    "endpoint": ep,
                    "distance": round(nearest_dist, 1),
                })

        # 去重设备
        seen_tags = set()
        unique_devices = []
        for cd in connected_devices:
            if cd["device"] not in seen_tags:
                seen_tags.add(cd["device"])
                unique_devices.append(cd)

        if len(unique_devices) >= 2:
            # 设备间通过管线连接
            for i in range(len(unique_devices)):
                for j in range(i + 1, len(unique_devices)):
                    connections.append({
                        "from_device": unique_devices[i]["device"],
                        "to_device": unique_devices[j]["device"],
                        "pipe_no": pipe["pipe_no"],
                        "medium": pipe["medium"],
                        "size": pipe.get("size"),
                        "file": pipe["file"],
                        "confidence": min(pipe.get("confidence", 0.5),
                                          0.9 - (unique_devices[i]["distance"] + unique_devices[j]["distance"]) / 2000),
                        "direction": "unknown",  # 流向待确定
                    })
        elif len(unique_devices) == 1:
            # 管线只连接一个设备（另一端可能在图纸外）
            connections.append({
                "from_device": unique_devices[0]["device"],
                "to_device": None,
                "pipe_no": pipe["pipe_no"],
                "medium": pipe["medium"],
                "size": pipe.get("size"),
                "file": pipe["file"],
                "confidence": 0.3,
                "direction": "unknown",
                "note": "仅连接到一个设备，另一端在图纸外或待确认",
            })

    return connections


def build_piping_network(docs: dict) -> dict:
    """从所有解析文档构建完整管线网络。"""
    all_pipes = []
    all_devices = []

    for sha, d in docs.items():
        cache = d.get("_cache") or d.get("structure") or {}
        if not cache:
            continue
        # 确保 cache 有 file_name
        if "file_name" not in cache and "file_name" in d:
            cache = {**cache, "file_name": d["file_name"]}
        pipes = extract_pipes_from_cad(cache)
        devices = extract_devices_from_cad(cache)
        all_pipes.extend(pipes)
        all_devices.extend(devices)

    connections = build_connections(all_pipes, all_devices)

    # 按设备分组管线
    device_pipes = {}
    for conn in connections:
        for dev_key in ["from_device", "to_device"]:
            dev = conn.get(dev_key)
            if dev:
                if dev not in device_pipes:
                    device_pipes[dev] = []
                if conn["pipe_no"] not in [p["pipe_no"] for p in device_pipes[dev]]:
                    device_pipes[dev].append({
                        "pipe_no": conn["pipe_no"],
                        "medium": conn["medium"],
                        "connected_to": conn["to_device"] if dev_key == "from_device" else conn["from_device"],
                        "file": conn["file"],
                    })

    # 保存
    m = _load()
    m["pipes"] = {p["pipe_no"]: p for p in all_pipes}
    m["connections"] = connections
    m["device_pipes"] = device_pipes
    _save(m)

    return {
        "total_pipes": len(all_pipes),
        "total_connections": len(connections),
        "devices_with_pipes": len(device_pipes),
        "pipes": all_pipes,
        "connections": connections,
        "device_pipes": device_pipes,
    }


# ---------------- 查询接口 ----------------

def get_device_pipes(tag: str) -> list:
    """获取指定设备连接的所有管线。"""
    m = _load()
    return m.get("device_pipes", {}).get(tag, [])


def get_device_connections(tag: str) -> list:
    """获取指定设备的所有连接关系。"""
    m = _load()
    conns = m.get("connections", [])
    return [c for c in conns if c.get("from_device") == tag or c.get("to_device") == tag]


def get_pipe_info(pipe_no: str) -> dict:
    """获取指定管线的详细信息。"""
    m = _load()
    return m.get("pipes", {}).get(pipe_no, {})


def list_all_pipes() -> list:
    """列出所有管线。"""
    m = _load()
    return list(m.get("pipes", {}).values())


def list_connections() -> list:
    """列出所有连接关系。"""
    m = _load()
    return m.get("connections", [])


def stats() -> dict:
    """管线网络统计。"""
    m = _load()
    pipes = list(m.get("pipes", {}).values())
    conns = m.get("connections", [])
    device_pipes = m.get("device_pipes", {})
    mediums = {}
    for p in pipes:
        med = p.get("medium", "未知")
        mediums[med] = mediums.get(med, 0) + 1
    return {
        "total_pipes": len(pipes),
        "total_connections": len(conns),
        "devices_with_pipes": len(device_pipes),
        "medium_distribution": mediums,
        "pipes_with_size": sum(1 for p in pipes if p.get("size")),
        "high_confidence_connections": sum(1 for c in conns if c.get("confidence", 0) >= 0.6),
    }
