"""
v0.1.58：设备安装位置与管线联动可视化

生成设备在车间中的位置分布 + 设备间管线连接关系的可视化图。
支持按车间筛选、按设备类型筛选，输出SVG/HTML格式。
"""

import os
import json
from typing import Optional



# v0.1.61：设备类型颜色映射（模块级常量）
DEVICE_TYPE_COLORS = {
    "泵": "#3498db",
    "压缩机": "#e74c3c",
    "塔器": "#9b59b6",
    "换热器": "#2ecc71",
    "容器": "#f39c12",
    "风机": "#1abc9c",
    "电机": "#34495e",
    "阀门": "#95a5a6",
    "储罐": "#e67e22",
    "其他": "#7f8c8d",
}

def _load_spatial_data():
    """加载空间模型和管线网络数据。"""
    try:
        from . import relations as _rel
        from . import spatial_model as _sm
        from . import piping_network as _pn
        g = _rel.load_relations()
        spatial = _sm.build_spatial_model(g)
        # 空间模型使用 device_index
        device_index = spatial.get("device_index", {})
        # relations 设备列表
        rel_devices = g.get("devices", [])
        
        # 合并设备信息
        devices = []
        for rd in rel_devices:
            tag = rd["tag"]
            sd = device_index.get(tag, {})
            # 获取坐标
            x = sd.get("x")
            y = sd.get("y")
            z = sd.get("z")
            # 如果空间模型没有坐标，尝试从cad_positions获取
            if x is None and rd.get("cad_positions"):
                cp = rd["cad_positions"][0] if rd["cad_positions"] else {}
                x = cp.get("x")
                y = cp.get("y")
                z = cp.get("z") or z
            # 车间
            workshop = sd.get("workshop") or (rd.get("workshops", [""])[0] if rd.get("workshops") else "")
            # 设备类型
            dev_type = sd.get("type") or ""
            if not dev_type:
                from . import equipment_types as _et
                dev_type = _et.get_equipment_type_from_devices([rd])
            # 名称
            name = sd.get("name") or rd.get("name", tag)
            
            devices.append({
                "tag": tag,
                "name": name,
                "type": dev_type,
                "workshop": workshop,
                "x": x,
                "y": y,
                "z": z,
            })
        
        # 构建管线网络
        try:
            network = _pn.build_piping_network()
        except Exception:
            network = {"pipes": [], "connections": []}
        return devices, network
    except Exception as e:
        import traceback
        traceback.print_exc()
        return [], {"pipes": [], "connections": []}


def _normalize_coordinates(devices, width=800, height=600, padding=60):
    """将设备坐标归一化到画布范围内。"""
    if not devices:
        return {}
    
    xs = [d.get("x") for d in devices if d.get("x") is not None]
    ys = [d.get("y") for d in devices if d.get("y") is not None]
    
    if not xs or not ys:
        # 没有坐标时按网格排列
        positions = {}
        cols = 3
        for i, d in enumerate(devices):
            row = i // cols
            col = i % cols
            positions[d["tag"]] = {
                "x": padding + col * (width - 2 * padding) / (cols - 1 if cols > 1 else 1),
                "y": padding + row * 80,
                "has_coord": False,
            }
        return positions
    
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    range_x = max_x - min_x if max_x > min_x else 1
    range_y = max_y - min_y if max_y > min_y else 1
    
    positions = {}
    for d in devices:
        tag = d["tag"]
        if d.get("x") is not None and d.get("y") is not None:
            nx = padding + (d["x"] - min_x) / range_x * (width - 2 * padding)
            ny = padding + (d["y"] - min_y) / range_y * (height - 2 * padding)
            positions[tag] = {"x": nx, "y": ny, "has_coord": True}
        else:
            positions[tag] = {"x": width / 2, "y": height / 2, "has_coord": False}
    
    return positions


def generate_spatial_svg(workshop: str = None, eq_type: str = None,
                          width: int = 900, height: int = 650) -> str:
    """生成设备安装位置与管线联动的SVG图。
    
    Args:
        workshop: 按车间筛选
        eq_type: 按设备类型筛选
        width: 画布宽度
        height: 画布高度
    
    Returns:
        SVG字符串
    """
    devices, network = _load_spatial_data()
    
    # 筛选
    if workshop:
        devices = [d for d in devices if d.get("workshop") == workshop]
    if eq_type:
        devices = [d for d in devices if d.get("type") == eq_type or eq_type in d.get("name", "")]
    
    if not devices:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><text x="{width//2}" y="{height//2}" text-anchor="middle" fill="#999" font-size="16">暂无设备位置数据</text></svg>'
    
    positions = _normalize_coordinates(devices, width, height)
    device_tags = {d["tag"] for d in devices}
    
    # 颜色映射
    type_colors = {
        "泵": "#3498db", "压缩机": "#e74c3c", "塔器": "#9b59b6",
        "换热器": "#1abc9c", "容器": "#f39c12", "风机": "#2ecc71",
        "电机": "#e67e22", "阀门": "#95a5a6", "储罐": "#34495e",
    }
    
    # 构建SVG
    svg_parts = []
    svg_parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" style="background:#f8f9fa;font-family:Arial,sans-serif;">')
    
    # 标题
    title = "设备安装位置与管线联动图"
    if workshop:
        title += f" - {workshop}"
    svg_parts.append(f'<text x="{width//2}" y="30" text-anchor="middle" font-size="18" font-weight="bold" fill="#2c3e50">{title}</text>')
    
    # 图例
    legend_x = width - 160
    legend_y = 50
    svg_parts.append(f'<rect x="{legend_x-10}" y="{legend_y-15}" width="150" height="120" fill="white" stroke="#ddd" rx="5"/>')
    svg_parts.append(f'<text x="{legend_x}" y="{legend_y}" font-size="12" font-weight="bold" fill="#333">图例</text>')
    svg_parts.append(f'<circle cx="{legend_x+8}" cy="{legend_y+20}" r="6" fill="#3498db"/><text x="{legend_x+20}" y="{legend_y+24}" font-size="11" fill="#555">有坐标设备</text>')
    svg_parts.append(f'<circle cx="{legend_x+8}" cy="{legend_y+40}" r="6" fill="#95a5a6" stroke-dasharray="3,3"/><text x="{legend_x+20}" y="{legend_y+44}" font-size="11" fill="#555">无坐标设备</text>')
    svg_parts.append(f'<line x1="{legend_x}" y1="{legend_y+60}" x2="{legend_x+20}" y2="{legend_y+60}" stroke="#e74c3c" stroke-width="2"/><text x="{legend_x+25}" y="{legend_y+64}" font-size="11" fill="#555">管线连接</text>')
    svg_parts.append(f'<text x="{legend_x}" y="{legend_y+85}" font-size="10" fill="#999">共{len(devices)}台设备</text>')
    
    # 绘制管线连接
    connections = network.get("connections", [])
    drawn_pipes = set()
    for conn in connections:
        from_dev = conn.get("from_device", "")
        to_dev = conn.get("to_device", "")
        pipe_no = conn.get("pipe_no", "")
        if from_dev in device_tags and to_dev in device_tags:
            key = f"{from_dev}-{to_dev}-{pipe_no}"
            if key not in drawn_pipes:
                drawn_pipes.add(key)
                p1 = positions.get(from_dev)
                p2 = positions.get(to_dev)
                if p1 and p2:
                    svg_parts.append(f'<line x1="{p1["x"]}" y1="{p1["y"]}" x2="{p2["x"]}" y2="{p2["y"]}" stroke="#e74c3c" stroke-width="1.5" opacity="0.6"/>')
                    # 管线编号标注
                    mid_x = (p1["x"] + p2["x"]) / 2
                    mid_y = (p1["y"] + p2["y"]) / 2
                    if pipe_no:
                        svg_parts.append(f'<text x="{mid_x}" y="{mid_y-3}" text-anchor="middle" font-size="9" fill="#e74c3c" opacity="0.8">{pipe_no}</text>')
    
    # 绘制设备
    for d in devices:
        tag = d["tag"]
        pos = positions.get(tag)
        if not pos:
            continue
        
        dev_type = d.get("type", "未知")
        color = type_colors.get(dev_type, "#3498db")
        name = d.get("name", tag)
        workshop = d.get("workshop", "")
        z = d.get("z")
        
        # 设备圆圈
        if pos["has_coord"]:
            svg_parts.append(f'<circle cx="{pos["x"]}" cy="{pos["y"]}" r="18" fill="{color}" stroke="white" stroke-width="2"/>')
        else:
            svg_parts.append(f'<circle cx="{pos["x"]}" cy="{pos["y"]}" r="18" fill="{color}" stroke="white" stroke-width="2" stroke-dasharray="4,2" opacity="0.7"/>')
        
        # 位号
        svg_parts.append(f'<text x="{pos["x"]}" y="{pos["y"]+4}" text-anchor="middle" font-size="10" fill="white" font-weight="bold">{tag}</text>')
        
        # 名称和车间
        label_y = pos["y"] + 35
        svg_parts.append(f'<text x="{pos["x"]}" y="{label_y}" text-anchor="middle" font-size="10" fill="#333">{name[:12]}</text>')
        if workshop:
            svg_parts.append(f'<text x="{pos["x"]}" y="{label_y+13}" text-anchor="middle" font-size="9" fill="#888">{workshop}</text>')
        if z is not None:
            svg_parts.append(f'<text x="{pos["x"]}" y="{label_y+25}" text-anchor="middle" font-size="9" fill="#16a085">EL+{z}m</text>')
    
    # 坐标轴
    axis_x = 50
    axis_y = height - 50
    svg_parts.append(f'<line x1="{axis_x}" y1="{axis_y}" x2="{axis_x+100}" y2="{axis_y}" stroke="#999" stroke-width="1"/>')
    svg_parts.append(f'<line x1="{axis_x}" y1="{axis_y}" x2="{axis_x}" y2="{axis_y-60}" stroke="#999" stroke-width="1"/>')
    svg_parts.append(f'<text x="{axis_x+105}" y="{axis_y+4}" font-size="10" fill="#999">X</text>')
    svg_parts.append(f'<text x="{axis_x-5}" y="{axis_y-65}" font-size="10" fill="#999">Y</text>')
    
    svg_parts.append('</svg>')
    return "\\n".join(svg_parts)


def generate_spatial_html(workshop: str = None, eq_type: str = None) -> str:
    """生成包含SVG的完整HTML页面。"""
    svg = generate_spatial_svg(workshop, eq_type)
    workshops = list_workshops()
    types = list_device_types()
    
    workshop_options = "".join(f'<option value="{w}" {"selected" if w == workshop else ""}>{w}</option>' for w in workshops)
    type_options = "".join(f'<option value="{t}" {"selected" if t == eq_type else ""}>{t}</option>' for t in types)
    
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>设备安装位置与管线联动图</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
.container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
h2 {{ color: #2c3e50; margin-top: 0; }}
.filters {{ margin-bottom: 15px; }}
.filters label {{ margin-right: 10px; font-size: 14px; }}
.filters select {{ padding: 5px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }}
.filters button {{ padding: 5px 15px; background: #1E5AA8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
.svg-container {{ overflow: auto; border: 1px solid #eee; border-radius: 4px; padding: 10px; }}
.info {{ margin-top: 15px; font-size: 13px; color: #666; }}
</style>
</head>
<body>
<div class="container">
<h2>设备安装位置与管线联动图</h2>
<div class="filters">
<label>车间：<select id="workshop"><option value="">全部</option>{workshop_options}</select></label>
<label>设备类型：<select id="eqtype"><option value="">全部</option>{type_options}</select></label>
<button onclick="filter()">筛选</button>
</div>
<div class="svg-container">
{svg}
</div>
<div class="info">
<p>说明：实线圆圈表示有CAD坐标的设备，虚线圆圈表示无坐标设备（按网格排列）。红色连线表示设备间的管线连接。</p>
</div>
</div>
<script>
function filter() {{
    var w = document.getElementById('workshop').value;
    var t = document.getElementById('eqtype').value;
    var url = '/api/spatial-visualization/html?';
    if (w) url += 'workshop=' + encodeURIComponent(w) + '&';
    if (t) url += 'eq_type=' + encodeURIComponent(t);
    window.location.href = url;
}}
</script>
</body>
</html>'''
    return html


def list_workshops() -> list:
    """列出所有车间。"""
    devices, _ = _load_spatial_data()
    workshops = sorted(set(d.get("workshop", "") for d in devices if d.get("workshop")))
    return workshops


def list_device_types() -> list:
    """列出所有设备类型。"""
    devices, _ = _load_spatial_data()
    types = sorted(set(d.get("type", "") for d in devices if d.get("type")))
    return types


def get_stats() -> dict:
    """获取可视化统计信息。"""
    devices, network = _load_spatial_data()
    workshops = list_workshops()
    types = list_device_types()
    connections = [c for c in network.get("connections", [])
                   if c.get("from_device") in {d["tag"] for d in devices}
                   and c.get("to_device") in {d["tag"] for d in devices}]
    has_coord = sum(1 for d in devices if d.get("x") is not None and d.get("y") is not None)
    has_elevation = sum(1 for d in devices if d.get("z") is not None)
    elevations = sorted(set(round(d["z"], 2) for d in devices if d.get("z") is not None))
    return {
        "total_devices": len(devices),
        "devices_with_coords": has_coord,
        "devices_without_coords": len(devices) - has_coord,
        "devices_with_elevation": has_elevation,
        "workshops": len(workshops),
        "device_types": len(types),
        "piping_connections": len(connections),
        "workshop_list": workshops,
        "type_list": types,
        "elevation_list": elevations,
    }


def list_elevations() -> list:
    """v0.1.61：列出所有标高层。"""
    devices, _ = _load_spatial_data()
    elevations = set()
    for d in devices:
        if d.get("z") is not None:
            elevations.add(round(d["z"], 2))
    return sorted(list(elevations))


def _group_devices_by_elevation(devices: list) -> tuple:
    """v0.1.61：按标高分组设备。"""
    groups = {}
    no_elevation = []
    for d in devices:
        if d.get("z") is not None:
            key = round(d["z"], 2)
            if key not in groups:
                groups[key] = []
            groups[key].append(d)
        else:
            no_elevation.append(d)
    return groups, no_elevation


def generate_elevation_layer_svg(elevation=None, workshop=None, device_type=None) -> str:
    """v0.1.61：生成指定标高层的设备位置SVG。"""
    devices, network = _load_spatial_data()
    filtered = []
    for d in devices:
        if workshop and d.get("workshop") != workshop:
            continue
        if device_type and d.get("type") != device_type:
            continue
        if elevation is None:
            if d.get("z") is not None:
                continue
        else:
            if d.get("z") is None or abs(d["z"] - elevation) > 0.1:
                continue
        filtered.append(d)
    coords = _normalize_coordinates(filtered)
    width, height = 1000, 700
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background:#f8f9fa;font-family:Arial,sans-serif">']
    title = f"设备位置分布图 - 标高 {elevation}m" if elevation is not None else "设备位置分布图 - 无标高设备"
    svg.append(f'<text x="{width//2}" y="30" text-anchor="middle" font-size="18" font-weight="bold" fill="#1E5AA8">{title}</text>')
    svg.append(f'<line x1="80" y1="{height-80}" x2="{width-40}" y2="{height-80}" stroke="#333" stroke-width="2"/>')
    svg.append(f'<line x1="80" y1="60" x2="80" y2="{height-80}" stroke="#333" stroke-width="2"/>')
    for i in range(1, 10):
        x = 80 + (width - 120) * i / 10
        y = 60 + (height - 140) * i / 10
        svg.append(f'<line x1="{x}" y1="60" x2="{x}" y2="{height-80}" stroke="#e0e0e0" stroke-width="0.5"/>')
        svg.append(f'<line x1="80" y1="{y}" x2="{width-40}" y2="{y}" stroke="#e0e0e0" stroke-width="0.5"/>')
    for d in filtered:
        tag = d["tag"]
        pos = coords.get(tag, {"x": width//2, "y": height//2})
        x, y = pos["x"], pos["y"]
        dev_type = d.get("type", "其他")
        color = DEVICE_TYPE_COLORS.get(dev_type, "#95a5a6")
        svg.append(f'<circle cx="{x}" cy="{y}" r="12" fill="{color}" stroke="#fff" stroke-width="2"/>')
        svg.append(f'<text x="{x+18}" y="{y+4}" font-size="11" fill="#333">{tag}</text>')
        if d.get("workshop"):
            svg.append(f'<text x="{x+18}" y="{y+18}" font-size="9" fill="#888">{d["workshop"]}</text>')
    legend_x = width - 180
    legend_y = 60
    svg.append(f'<rect x="{legend_x}" y="{legend_y}" width="170" height="200" fill="white" stroke="#ddd" rx="5"/>')
    svg.append(f'<text x="{legend_x+10}" y="{legend_y+20}" font-size="12" font-weight="bold" fill="#333">设备类型图例</text>')
    for i, (dtype, color) in enumerate(DEVICE_TYPE_COLORS.items()):
        ly = legend_y + 40 + i * 18
        svg.append(f'<circle cx="{legend_x+20}" cy="{ly}" r="6" fill="{color}"/>')
        svg.append(f'<text x="{legend_x+35}" y="{ly+4}" font-size="10" fill="#555">{dtype}</text>')
    svg.append(f'<text x="90" y="{height-30}" font-size="11" fill="#666">设备总数: {len(filtered)} | 标高: {elevation if elevation is not None else "无"}</text>')
    svg.append('</svg>')
    return "\n".join(svg)


def generate_elevation_stack_svg(workshop=None, device_type=None) -> str:
    """v0.1.61：生成分层堆叠视图（所有标高层同时展示）。"""
    devices, _ = _load_spatial_data()
    filtered = []
    for d in devices:
        if workshop and d.get("workshop") != workshop:
            continue
        if device_type and d.get("type") != device_type:
            continue
        filtered.append(d)
    groups, no_elevation = _group_devices_by_elevation(filtered)
    elevations = sorted(groups.keys())
    layer_height = 180
    width = 1000
    total_layers = len(elevations) + (1 if no_elevation else 0)
    height = 60 + total_layers * layer_height + 40
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background:#f8f9fa;font-family:Arial,sans-serif">']
    svg.append(f'<text x="{width//2}" y="30" text-anchor="middle" font-size="18" font-weight="bold" fill="#1E5AA8">设备位置分层堆叠视图（按标高）</text>')
    all_layers = [(e, groups[e]) for e in elevations]
    if no_elevation:
        all_layers.append((None, no_elevation))
    for layer_idx, (elev, layer_devices) in enumerate(all_layers):
        layer_y = 60 + layer_idx * layer_height
        bg_color = "#ffffff" if layer_idx % 2 == 0 else "#f0f4f8"
        svg.append(f'<rect x="60" y="{layer_y}" width="{width-100}" height="{layer_height-10}" fill="{bg_color}" stroke="#ddd" rx="5"/>')
        title = f"标高 {elev}m" if elev is not None else "无标高设备"
        svg.append(f'<text x="80" y="{layer_y+25}" font-size="14" font-weight="bold" fill="#1E5AA8">{title}（{len(layer_devices)}台）</text>')
        cols = min(8, max(1, len(layer_devices)))
        rows = (len(layer_devices) + cols - 1) // cols
        cell_w = (width - 200) / cols
        cell_h = (layer_height - 60) / max(1, rows)
        for i, d in enumerate(layer_devices):
            col = i % cols
            row = i // cols
            x = 100 + col * cell_w + cell_w / 2
            y = layer_y + 50 + row * cell_h + cell_h / 2
            dev_type = d.get("type", "其他")
            color = DEVICE_TYPE_COLORS.get(dev_type, "#95a5a6")
            svg.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{color}" stroke="#fff" stroke-width="2"/>')
            svg.append(f'<text x="{x}" y="{y+25}" text-anchor="middle" font-size="10" fill="#333">{d["tag"]}</text>')
            if d.get("workshop"):
                svg.append(f'<text x="{x}" y="{y+38}" text-anchor="middle" font-size="8" fill="#888">{d["workshop"]}</text>')
    legend_x = width - 160
    legend_y = 60
    svg.append(f'<rect x="{legend_x}" y="{legend_y}" width="150" height="180" fill="white" stroke="#ddd" rx="5"/>')
    svg.append(f'<text x="{legend_x+10}" y="{legend_y+20}" font-size="11" font-weight="bold" fill="#333">设备类型</text>')
    for i, (dtype, color) in enumerate(DEVICE_TYPE_COLORS.items()):
        ly = legend_y + 38 + i * 16
        svg.append(f'<circle cx="{legend_x+18}" cy="{ly}" r="5" fill="{color}"/>')
        svg.append(f'<text x="{legend_x+30}" y="{ly+3}" font-size="9" fill="#555">{dtype}</text>')
    svg.append('</svg>')
    return "\n".join(svg)
