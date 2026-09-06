"""
v0.1.64：设备安装位置与施工进度联动

根据设备位置（车间、标高、坐标）自动安排施工顺序，生成施工进度甘特图，
管理设备施工状态，识别关键路径。
"""

import os
import json
import datetime
from typing import Optional


_SCHEDULE_FILE = os.path.join("data", "construction_schedule.json")
_DEVICE_STATUS_FILE = os.path.join("data", "device_status.json")


def _ensure_dirs():
    os.makedirs("data", exist_ok=True)


def _load_schedule() -> dict:
    if os.path.exists(_SCHEDULE_FILE):
        try:
            with open(_SCHEDULE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_schedule(schedule: dict):
    _ensure_dirs()
    with open(_SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)


def _load_device_status() -> dict:
    if os.path.exists(_DEVICE_STATUS_FILE):
        try:
            with open(_DEVICE_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_device_status(status: dict):
    _ensure_dirs()
    with open(_DEVICE_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def auto_schedule_devices(start_date: str = None,
                          days_per_device: int = 2,
                          workshop_parallel: int = 1) -> dict:
    """v0.1.64：根据设备位置自动安排施工顺序。
    
    排序规则：
    1. 按车间分组
    2. 同一车间内按标高从低到高（先安装低层设备）
    3. 同一标高内按x坐标从左到右
    4. 大型设备/关键设备优先
    
    Args:
        start_date: 开始日期（YYYY-MM-DD），默认今天
        days_per_device: 每台设备施工天数
        workshop_parallel: 并行施工的车间数
    
    Returns:
        施工进度安排
    """
    from . import relations as _rel
    from . import spatial_model as _sm
    
    g = _rel.load_relations()
    spatial = _sm.build_spatial_model(g)
    spatial_devs = {d["tag"]: d for d in spatial.get("devices", [])}
    
    devices = g.get("devices", [])
    
    # 构建设备位置信息
    device_info = []
    for d in devices:
        tag = d["tag"]
        sd = spatial_devs.get(tag, {})
        workshop = sd.get("workshop") or (d.get("workshops", [""])[0] if d.get("workshops") else "")
        z = sd.get("z")
        x = sd.get("x")
        y = sd.get("y")
        
        # 判断是否关键设备（大型设备）
        dev_type = sd.get("type", "")
        is_critical = dev_type in ["塔器", "压缩机", "储罐", "换热器"]
        
        device_info.append({
            "tag": tag,
            "name": sd.get("name", tag),
            "type": dev_type,
            "workshop": workshop,
            "z": z if z is not None else 999,  # 无标高的排最后
            "x": x if x is not None else 0,
            "y": y if y is not None else 0,
            "is_critical": is_critical,
            "sources": d.get("sources", {}),
        })
    
    # 排序：车间 → 关键设备优先 → 标高从低到高 → x从左到右
    device_info.sort(key=lambda d: (
        d["workshop"] or "",
        not d["is_critical"],  # 关键设备优先
        d["z"],
        d["x"],
    ))
    
    # 安排日期
    if not start_date:
        start_date = datetime.date.today().isoformat()
    
    start = datetime.date.fromisoformat(start_date)
    
    # 按车间分组并行安排
    workshops = sorted(set(d["workshop"] for d in device_info if d["workshop"]))
    workshop_schedules = {w: [] for w in workshops}
    
    for d in device_info:
        ws = d["workshop"] or "未分配"
        if ws not in workshop_schedules:
            workshop_schedules[ws] = []
        workshop_schedules[ws].append(d)
    
    # 生成施工进度
    schedule_items = []
    current_date = start
    
    # 简单串行安排（后续可优化为并行）
    for d in device_info:
        item = {
            "tag": d["tag"],
            "name": d["name"],
            "type": d["type"],
            "workshop": d["workshop"],
            "elevation": d["z"] if d["z"] != 999 else None,
            "is_critical": d["is_critical"],
            "start_date": current_date.isoformat(),
            "end_date": (current_date + datetime.timedelta(days=days_per_device - 1)).isoformat(),
            "duration_days": days_per_device,
            "status": "pending",  # pending/in_progress/completed
        }
        schedule_items.append(item)
        current_date += datetime.timedelta(days=days_per_device)
    
    # 识别关键路径（关键设备连续施工的路径）
    critical_path = [item for item in schedule_items if item["is_critical"]]
    
    schedule = {
        "generated_at": datetime.datetime.now().isoformat(),
        "start_date": start_date,
        "end_date": schedule_items[-1]["end_date"] if schedule_items else start_date,
        "total_devices": len(schedule_items),
        "total_days": (current_date - start).days,
        "workshops": workshops,
        "critical_path_count": len(critical_path),
        "items": schedule_items,
    }
    
    _save_schedule(schedule)
    
    return schedule


def update_device_status(tag: str, status: str, notes: str = "") -> dict:
    """v0.1.64：更新设备施工状态。
    
    Args:
        tag: 设备位号
        status: 状态 - pending/in_progress/completed
        notes: 备注
    
    Returns:
        更新结果
    """
    valid_status = ["pending", "in_progress", "completed"]
    if status not in valid_status:
        return {"error": "无效状态", "valid_status": valid_status}
    
    status_data = _load_device_status()
    status_data[tag] = {
        "status": status,
        "notes": notes,
        "updated_at": datetime.datetime.now().isoformat(),
    }
    _save_device_status(status_data)
    
    # 同步更新施工进度中的状态
    schedule = _load_schedule()
    if schedule.get("items"):
        for item in schedule["items"]:
            if item["tag"] == tag:
                item["status"] = status
                break
        _save_schedule(schedule)
    
    return {"ok": True, "tag": tag, "status": status, "notes": notes}


def get_device_status(tag: str = None) -> dict:
    """v0.1.64：获取设备施工状态。"""
    status_data = _load_device_status()
    if tag:
        return {"ok": True, "tag": tag, **status_data.get(tag, {"status": "pending"})}
    return {"ok": True, "devices": status_data}


def get_schedule_stats() -> dict:
    """v0.1.64：获取施工进度统计。"""
    schedule = _load_schedule()
    status_data = _load_device_status()
    
    if not schedule.get("items"):
        return {"ok": True, "total_devices": 0, "message": "尚未生成施工进度，请先调用auto_schedule_devices"}
    
    items = schedule["items"]
    total = len(items)
    pending = sum(1 for i in items if i.get("status") == "pending")
    in_progress = sum(1 for i in items if i.get("status") == "in_progress")
    completed = sum(1 for i in items if i.get("status") == "completed")
    
    # 按车间统计
    workshop_stats = {}
    for item in items:
        ws = item.get("workshop", "未分配")
        if ws not in workshop_stats:
            workshop_stats[ws] = {"total": 0, "completed": 0, "in_progress": 0, "pending": 0}
        workshop_stats[ws]["total"] += 1
        workshop_stats[ws][item.get("status", "pending")] += 1
    
    # 计算进度百分比
    progress = (completed / total * 100) if total > 0 else 0
    
    return {
        "ok": True,
        "total_devices": total,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "progress_percent": round(progress, 1),
        "start_date": schedule.get("start_date"),
        "end_date": schedule.get("end_date"),
        "total_days": schedule.get("total_days"),
        "workshop_stats": workshop_stats,
        "critical_path_count": schedule.get("critical_path_count", 0),
    }


def generate_gantt_svg(workshop: str = None) -> str:
    """v0.1.64：生成施工进度甘特图SVG。
    
    Args:
        workshop: 车间筛选
    
    Returns:
        SVG字符串
    """
    schedule = _load_schedule()
    items = schedule.get("items", [])
    
    if not items:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200"><text x="400" y="100" text-anchor="middle">尚未生成施工进度</text></svg>'
    
    # 筛选
    if workshop:
        items = [i for i in items if i.get("workshop") == workshop]
    
    # 计算日期范围
    start_dates = [datetime.date.fromisoformat(i["start_date"]) for i in items]
    end_dates = [datetime.date.fromisoformat(i["end_date"]) for i in items]
    min_date = min(start_dates)
    max_date = max(end_dates)
    total_days = (max_date - min_date).days + 1
    
    # SVG尺寸
    row_height = 28
    header_height = 50
    left_width = 180
    day_width = max(15, 600 // total_days)
    width = left_width + total_days * day_width + 40
    height = header_height + len(items) * row_height + 40
    
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="background:#fff;font-family:Arial,sans-serif">']
    
    # 标题
    svg.append(f'<text x="{width//2}" y="25" text-anchor="middle" font-size="16" font-weight="bold" fill="#1E5AA8">设备安装施工进度甘特图</text>')
    
    # 日期表头
    for day in range(total_days):
        date = min_date + datetime.timedelta(days=day)
        x = left_width + day * day_width
        # 周末高亮
        if date.weekday() >= 5:
            svg.append(f'<rect x="{x}" y="{header_height-20}" width="{day_width}" height="{height-header_height-20}" fill="#f0f0f0"/>')
        # 日期标签（每7天显示一次）
        if day % 7 == 0 or day == total_days - 1:
            svg.append(f'<text x="{x + day_width//2}" y="{header_height-5}" text-anchor="middle" font-size="9" fill="#666">{date.strftime("%m-%d")}</text>')
    
    # 今天线
    today = datetime.date.today()
    if min_date <= today <= max_date:
        today_offset = (today - min_date).days
        today_x = left_width + today_offset * day_width
        svg.append(f'<line x1="{today_x}" y1="{header_height-20}" x2="{today_x}" y2="{height-20}" stroke="#e74c3c" stroke-width="2" stroke-dasharray="4,2"/>')
        svg.append(f'<text x="{today_x+5}" y="{header_height-25}" font-size="10" fill="#e74c3c">今天</text>')
    
    # 设备行
    status_colors = {
        "pending": "#bdc3c7",
        "in_progress": "#f39c12",
        "completed": "#2ecc71",
    }
    
    for idx, item in enumerate(items):
        y = header_height + idx * row_height
        
        # 行背景交替
        if idx % 2 == 0:
            svg.append(f'<rect x="0" y="{y}" width="{width}" height="{row_height}" fill="#fafafa"/>')
        
        # 设备标签
        tag = item["tag"]
        name = item.get("name", tag)
        ws = item.get("workshop", "")
        label = f"{tag} {ws}"
        svg.append(f'<text x="10" y="{y+18}" font-size="11" fill="#333">{label[:25]}</text>')
        
        # 甘特条
        start_offset = (datetime.date.fromisoformat(item["start_date"]) - min_date).days
        duration = item.get("duration_days", 1)
        bar_x = left_width + start_offset * day_width
        bar_width = duration * day_width - 2
        bar_y = y + 5
        bar_height = row_height - 10
        color = status_colors.get(item.get("status", "pending"), "#bdc3c7")
        
        svg.append(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_width}" height="{bar_height}" fill="{color}" rx="3"/>')
        
        # 关键设备标记
        if item.get("is_critical"):
            svg.append(f'<rect x="{bar_x-3}" y="{bar_y-2}" width="{bar_width+6}" height="{bar_height+4}" fill="none" stroke="#e74c3c" stroke-width="1.5" rx="4"/>')
        
        # 状态文字
        status_text = {"pending": "待施工", "in_progress": "进行中", "completed": "已完成"}
        svg.append(f'<text x="{bar_x + bar_width//2}" y="{bar_y + bar_height//2 + 4}" text-anchor="middle" font-size="9" fill="#fff">{status_text.get(item.get("status"), "")}</text>')
    
    # 图例
    legend_y = height - 25
    legend_x = left_width
    svg.append(f'<rect x="{legend_x}" y="{legend_y-12}" width="12" height="12" fill="#bdc3c7" rx="2"/>')
    svg.append(f'<text x="{legend_x+18}" y="{legend_y-2}" font-size="10" fill="#666">待施工</text>')
    svg.append(f'<rect x="{legend_x+80}" y="{legend_y-12}" width="12" height="12" fill="#f39c12" rx="2"/>')
    svg.append(f'<text x="{legend_x+98}" y="{legend_y-2}" font-size="10" fill="#666">进行中</text>')
    svg.append(f'<rect x="{legend_x+160}" y="{legend_y-12}" width="12" height="12" fill="#2ecc71" rx="2"/>')
    svg.append(f'<text x="{legend_x+178}" y="{legend_y-2}" font-size="10" fill="#666">已完成</text>')
    svg.append(f'<rect x="{legend_x+240}" y="{legend_y-14}" width="14" height="16" fill="none" stroke="#e74c3c" stroke-width="1.5" rx="3"/>')
    svg.append(f'<text x="{legend_x+262}" y="{legend_y-2}" font-size="10" fill="#666">关键设备</text>')
    
    svg.append('</svg>')
    return "\\n".join(svg)


def list_workshops_in_schedule() -> list:
    """v0.1.64：列出施工进度中的车间。"""
    schedule = _load_schedule()
    items = schedule.get("items", [])
    workshops = sorted(set(i.get("workshop", "未分配") for i in items))
    return workshops
