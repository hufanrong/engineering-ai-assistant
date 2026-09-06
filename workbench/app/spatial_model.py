# 繁工AI 本地解析工作台 - 设备安装位置空间关系模型（v0.1.35）
# 目的：基于 CAD 坐标 + 设备台账 + 车间划分，建立 AI 可读的类3D空间结构。
#       让 AI 能理解"P-101 在哪个车间、什么位置、旁边是什么设备"。
#
# 口径（用户锁定）：
#   - 不用真正的三维模型，能理解空间结构就可以
#   - 空间数据主要来自图纸，车间有哪些设备来自台账文件
#   - 有些时候图纸上没有标注设备，台账中会有记录
#   - 将有关联的数据联系起来，建立一个类似3d效果的数据库，Ai可以读取

import math
import os
import json
from . import config
from . import elevation as _elev
import json
import os

from . import config


# 相邻设备判定阈值（米）。CAD 坐标按毫米计，除以 1000 得米。
NEIGHBOR_RADIUS_METERS = 15.0


def build_spatial_model(relations_graph: dict, elevation_map: dict = None) -> dict:
    """从 relations 图谱构建设备空间结构模型（v0.1.38：含标高 z 坐标）。
    返回 {workshops: {ws: {devices: [...]}}, device_index: {tag: {...}}, stats: {...}}。"""
    devices = relations_graph.get("devices", [])
    layout = relations_graph.get("layout", [])
    workshops_graph = relations_graph.get("workshops", [])

    # v0.1.38：加载设备标高映射（从台账/CAD/OCR 提取）
    if elevation_map is None:
        elevation_map = _load_elevation_from_cache()

    # layout 映射：tag → 确认的车间
    layout_map = {}
    for row in layout:
        if row.get("workshop"):
            layout_map[row["tag"]] = row["workshop"]

    # 构建设备空间索引
    device_index = {}
    for dev in devices:
        tag = dev["tag"]
        # 车间优先级：layout 确认 > devices.workshops 第一个
        workshop = layout_map.get(tag) or (dev.get("workshops") or [None])[0]

        # CAD 坐标（取第一个有坐标的）
        cad_positions = dev.get("cad_positions", [])
        primary_pos = cad_positions[0] if cad_positions else None
        has_cad_coords = primary_pos is not None

        # 来源类型
        sources = dev.get("sources", {})
        source_types = []
        if sources.get("cad", 0) > 0:
            source_types.append("cad")
        if sources.get("excel", 0) > 0:
            source_types.append("excel")
        if sources.get("ocr", 0) > 0:
            source_types.append("ocr")
        if sources.get("text", 0) > 0:
            source_types.append("text")

        # 坐标状态
        if has_cad_coords:
            coord_status = "图纸标注"
        elif "excel" in source_types:
            coord_status = "台账记录（图纸未标注）"
        else:
            coord_status = "位置待确认"

        device_index[tag] = {
            "tag": tag,
            "workshop": workshop,
            "x": primary_pos.get("x") if primary_pos else None,
            "y": primary_pos.get("y") if primary_pos else None,
            "z": elevation_map.get(tag, {}).get("elevation_m"),
            "z_source": elevation_map.get(tag, {}).get("source_type") if elevation_map.get(tag) else None,
            "z_confidence": elevation_map.get(tag, {}).get("confidence", 0) if elevation_map.get(tag) else 0,
            "z_note": elevation_map.get(tag, {}).get("note", "") if elevation_map.get(tag) else "",
            "has_cad_coords": has_cad_coords,
            "coord_status": coord_status,
            "sources": source_types,
            "cad_positions": cad_positions,
            "drawing_files": dev.get("files", []),
            "neighbors": [],  # 稍后计算
        }

    # 计算相邻设备（同车间内，基于 CAD 坐标）
    _compute_neighbors(device_index)

    # 按车间分组
    workshops = {}
    for tag, dev in device_index.items():
        ws = dev["workshop"] or "未分配车间"
        if ws not in workshops:
            workshops[ws] = {"workshop": ws, "devices": [], "device_count": 0,
                              "cad_annotated": 0, "excel_only": 0, "pending": 0}
        workshops[ws]["devices"].append(tag)
        workshops[ws]["device_count"] += 1
        if dev["has_cad_coords"]:
            workshops[ws]["cad_annotated"] += 1
        elif dev["coord_status"] == "台账记录（图纸未标注）":
            workshops[ws]["excel_only"] += 1
        else:
            workshops[ws]["pending"] += 1

    # 车间内设备按坐标排序（有坐标的排前面，按 x+y 排序）
    for ws in workshops.values():
        ws["devices"].sort(key=lambda t: (
            0 if device_index[t]["has_cad_coords"] else 1,
            (device_index[t]["x"] or 0) + (device_index[t]["y"] or 0)
        ))

    stats = {
        "total_devices": len(device_index),
        "workshops": len(workshops),
        "cad_annotated": sum(1 for d in device_index.values() if d["has_cad_coords"]),
        "excel_only": sum(1 for d in device_index.values() if d["coord_status"] == "台账记录（图纸未标注）"),
        "pending_location": sum(1 for d in device_index.values() if d["coord_status"] == "位置待确认"),
        "with_elevation": sum(1 for d in device_index.values() if d.get("z") is not None),
        "elevation_sources": _count_elevation_sources(device_index),
        "neighbor_radius_meters": NEIGHBOR_RADIUS_METERS,
    }

    return {
        "workshops": workshops,
        "device_index": device_index,
        "stats": stats,
    }


def _compute_neighbors(device_index: dict):
    """同车间内基于 CAD 坐标计算相邻设备。"""
    # 按车间分组
    by_workshop = {}
    for tag, dev in device_index.items():
        if dev["has_cad_coords"] and dev["workshop"]:
            by_workshop.setdefault(dev["workshop"], []).append(tag)

    for ws, tags in by_workshop.items():
        for i, t1 in enumerate(tags):
            d1 = device_index[t1]
            for j, t2 in enumerate(tags):
                if i >= j:
                    continue
                d2 = device_index[t2]
                dx = (d1["x"] or 0) - (d2["x"] or 0)
                dy = (d1["y"] or 0) - (d2["y"] or 0)
                dist_mm = math.sqrt(dx * dx + dy * dy)
                dist_m = dist_mm / 1000.0
                if dist_m <= NEIGHBOR_RADIUS_METERS:
                    d1["neighbors"].append({"tag": t2, "distance_m": round(dist_m, 2)})
                    d2["neighbors"].append({"tag": t1, "distance_m": round(dist_m, 2)})

    # 邻居按距离排序
    for dev in device_index.values():
        dev["neighbors"].sort(key=lambda n: n["distance_m"])


def _load_elevation_from_cache() -> dict:
    """从 parsed_cache 加载所有已解析文档，构建设备标高映射。"""
    cache_dir = os.path.join(config.DATA_DIR, "parsed_cache")
    docs = {}
    if os.path.exists(cache_dir):
        for fn in os.listdir(cache_dir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(cache_dir, fn), encoding="utf-8") as f:
                    d = json.load(f)
                docs[fn[:-5]] = d
            except Exception:  # noqa: BLE001
                pass
    return _elev.build_elevation_map(docs)


def _count_elevation_sources(device_index: dict) -> dict:
    """统计标高来源分布。"""
    counts = {}
    for d in device_index.values():
        src = d.get("z_source")
        if src:
            counts[src] = counts.get(src, 0) + 1
    return counts


def find_neighbors(spatial: dict, tag: str, radius_meters: float = None) -> list:
    """查找指定设备的相邻设备。"""
    dev = spatial["device_index"].get(tag)
    if not dev:
        return []
    radius = radius_meters or NEIGHBOR_RADIUS_METERS
    return [n for n in dev["neighbors"] if n["distance_m"] <= radius]


def get_workshop_layout(spatial: dict, workshop: str) -> dict:
    """获取指定车间的设备布局（按坐标排序）。"""
    ws = spatial["workshops"].get(workshop)
    if not ws:
        return {"workshop": workshop, "devices": [], "device_count": 0}
    devices = []
    for tag in ws["devices"]:
        d = spatial["device_index"][tag]
        devices.append({
            "tag": tag,
            "x": d["x"], "y": d["y"], "z": d.get("z"),
            "z_source": d.get("z_source"), "z_confidence": d.get("z_confidence", 0),
            "coord_status": d["coord_status"],
            "sources": d["sources"],
            "neighbor_count": len(d["neighbors"]),
        })
    return {
        "workshop": workshop,
        "devices": devices,
        "device_count": ws["device_count"],
        "cad_annotated": ws["cad_annotated"],
        "excel_only": ws["excel_only"],
        "pending": ws["pending"],
    }


def generate_ai_summary(spatial: dict) -> str:
    """生成 AI 可读的空间结构文本摘要。
    让 AI 能像人一样理解工程空间布局。"""
    lines = []
    stats = spatial["stats"]
    lines.append(f"【项目空间结构概览】")
    lines.append(f"共 {stats['workshops']} 个车间，{stats['total_devices']} 台设备。")
    lines.append(f"其中图纸标注坐标 {stats['cad_annotated']} 台，台账记录（图纸未标注）{stats['excel_only']} 台，位置待确认 {stats['pending_location']} 台。")
    lines.append(f"相邻设备判定半径：{stats['neighbor_radius_meters']} 米。")
    if stats.get("with_elevation", 0) > 0:
        elev_src = stats.get("elevation_sources", {})
        src_str = "、".join(f"{k}:{v}台" for k, v in elev_src.items())
        lines.append(f"已提取标高 {stats['with_elevation']} 台（来源：{src_str}）。")
    lines.append("")

    for ws_name, ws in sorted(spatial["workshops"].items()):
        lines.append(f"【{ws_name}】共 {ws['device_count']} 台设备"
                     f"（图纸标注 {ws['cad_annotated']} 台，台账未标注 {ws['excel_only']} 台，待确认 {ws['pending']} 台）：")

        # 有坐标的设备按位置描述
        cad_devices = [t for t in ws["devices"] if spatial["device_index"][t]["has_cad_coords"]]
        if cad_devices:
            lines.append("  图纸标注设备（按位置排序）：")
            for tag in cad_devices[:30]:  # 最多列30台
                d = spatial["device_index"][tag]
                neighbor_tags = [n["tag"] for n in d["neighbors"][:5]]
                nb_str = f"，相邻设备：{', '.join(neighbor_tags)}" if neighbor_tags else ""
                elev_str = ""
                if d.get("z") is not None:
                    elev_str = f", 标高 z={d['z']}m"
                    if d.get("z_note"):
                        elev_str += f"（{d['z_note']}）"
                lines.append(f"    - {tag}（坐标 x={d['x']}, y={d['y']}{elev_str}{nb_str}）")
            if len(cad_devices) > 30:
                lines.append(f"    ... 另有 {len(cad_devices) - 30} 台")

        # 台账记录但图纸未标注的设备
        excel_devices = [t for t in ws["devices"]
                         if spatial["device_index"][t]["coord_status"] == "台账记录（图纸未标注）"]
        if excel_devices:
            lines.append(f"  台账记录但图纸未标注设备（{len(excel_devices)} 台）：")
            lines.append(f"    {', '.join(excel_devices[:20])}")
            if len(excel_devices) > 20:
                lines.append(f"    ... 另有 {len(excel_devices) - 20} 台")

        # 位置待确认
        pending = [t for t in ws["devices"]
                   if spatial["device_index"][t]["coord_status"] == "位置待确认"]
        if pending:
            lines.append(f"  位置待确认设备（{len(pending)} 台）：{', '.join(pending[:10])}")

        lines.append("")

    return "\n".join(lines)


def save_spatial(spatial: dict, path: str = None):
    """保存空间模型到文件。"""
    if path is None:
        path = os.path.join(config.DATA_DIR, "spatial_model.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spatial, f, ensure_ascii=False, indent=2)
    return path


def load_spatial(path: str = None) -> dict:
    """加载空间模型。"""
    if path is None:
        path = os.path.join(config.DATA_DIR, "spatial_model.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)
