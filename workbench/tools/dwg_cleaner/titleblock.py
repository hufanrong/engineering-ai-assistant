# -*- coding: utf-8 -*-
"""图框检测、排序、标题栏区域定位与真实边界识别。

纯几何逻辑，不依赖 AutoCAD。矩形统一用 (minx, miny, maxx, maxy) 表示，
坐标与世界坐标一致（y 轴向上）。

2026-10-25 全情况整改（v0.1.156）：
- Frame 增加 rotation（斜置图框转正后的角度，单位弧度，默认 0）
- titleblock_region 支持四角/右侧/底部配置（corner）
- detect_titleblock_region：在右下角候选区锁定标题栏真实小矩形（防误删/漏删）
- is_portrait：竖版判断
- rotate_point：坐标按旋转角变换（斜置图框文字判定用）
"""

import math

STANDARD_SIZES_MM = [(841, 1189), (594, 841), (420, 594), (297, 420), (210, 297)]

# 标题栏位置配置取值
CORNER_BOTTOM_RIGHT = "bottom_right"
CORNER_BOTTOM = "bottom"
CORNER_TOP_RIGHT = "top_right"
CORNER_TOP_LEFT = "top_left"
CORNER_RIGHT = "right"
VALID_CORNERS = (CORNER_BOTTOM_RIGHT, CORNER_BOTTOM, CORNER_TOP_RIGHT,
                 CORNER_TOP_LEFT, CORNER_RIGHT)


class Frame:
    """一张图纸的矩形范围。rotation 为斜置图框转正角度（弧度，默认 0）。"""

    __slots__ = ("minx", "miny", "maxx", "maxy", "rotation")

    def __init__(self, minx, miny, maxx, maxy, rotation=0.0):
        self.minx, self.miny, self.maxx, self.maxy = minx, miny, maxx, maxy
        self.rotation = rotation

    @property
    def width(self):
        return self.maxx - self.minx

    @property
    def height(self):
        return self.maxy - self.miny

    @property
    def cx(self):
        return (self.minx + self.maxx) / 2.0

    @property
    def cy(self):
        return (self.miny + self.maxy) / 2.0

    def __repr__(self):
        return "Frame(%.1f,%.1f,%.1f,%.1f,rot=%.3f)" % (
            self.minx, self.miny, self.maxx, self.maxy, self.rotation)


def is_portrait(frame, ratio=1.05):
    """竖版判断：高明显大于宽视为竖版（长边竖直）。"""
    return frame.height > frame.width * ratio


def rotate_point(x, y, cx, cy, angle_rad):
    """把点绕 (cx, cy) 旋转 -angle_rad（把斜置坐标转回图框正轴系）。"""
    if not angle_rad:
        return (x, y)
    cos, sin = math.cos(angle_rad), math.sin(angle_rad)
    dx, dy = x - cx, y - cy
    return (cx + dx * cos - dy * sin, cy + dx * sin + dy * cos)


def match_standard_size(w, h, std_sizes=STANDARD_SIZES_MM, tolerance=3.0):
    """宽高是否命中标准图幅（含加长幅面：长边 = 标准长边 + k * 短边/4）。"""
    a, b = min(w, h), max(w, h)
    if a <= 0:
        return False
    for sw, sh in std_sizes:
        s_short, s_long = min(sw, sh), max(sw, sh)
        if abs(a - s_short) <= tolerance:
            step = s_short / 4.0
            for k in range(0, 9):
                if abs(b - (s_long + k * step)) <= tolerance:
                    return True
    return False


def match_fallback(w, h, min_side=180, max_side=1300, ratio_min=0.4, ratio_max=2.5):
    """放宽条件的矩形判定（用于标准图幅检测失败时的兜底）。"""
    a, b = min(w, h), max(w, h)
    if a < min_side or b > max_side:
        return False
    r = b / a if a > 0 else 999.0
    return ratio_min <= r <= ratio_max


def detect_frames(rects, cfg=None, use_fallback=True):
    """从候选矩形列表中过滤出图框，并去除嵌套（保留外层大框）。

    rects 元素：(minx, miny, maxx, maxy) 或 (minx, miny, maxx, maxy, rotation)。
    返回 Frame 列表（未排序）。
    """
    cfg = cfg or {}
    fd = cfg.get("frame_detect", {})
    std = fd.get("standard_sizes_mm", STANDARD_SIZES_MM)
    tol = fd.get("tolerance_mm", 3)

    def _unpack(r):
        if len(r) >= 5:
            return r[0], r[1], r[2], r[3], float(r[4])
        return r[0], r[1], r[2], r[3], 0.0

    candidates = []
    for r in rects:
        minx, miny, maxx, maxy, rot = _unpack(r)
        w, h = maxx - minx, maxy - miny
        if w <= 1e-9 or h <= 1e-9:
            continue
        if match_standard_size(w, h, std, tol):
            candidates.append(Frame(minx, miny, maxx, maxy, rot))

    if not candidates and use_fallback:
        f_min = fd.get("fallback_min_side_mm", 180)
        f_max = fd.get("fallback_max_side_mm", 1300)
        r_min = fd.get("fallback_ratio_min", 0.4)
        r_max = fd.get("fallback_ratio_max", 2.5)
        for r in rects:
            minx, miny, maxx, maxy, rot = _unpack(r)
            w, h = maxx - minx, maxy - miny
            if w <= 1e-9 or h <= 1e-9:
                continue
            if match_fallback(w, h, f_min, f_max, r_min, r_max):
                candidates.append(Frame(minx, miny, maxx, maxy, rot))

    # 去嵌套：面积大者优先，被已保留框完全包含的丢弃
    kept = []
    for c in sorted(candidates, key=lambda f: f.width * f.height, reverse=True):
        contained = False
        for k in kept:
            if (k.minx - 1e-6 <= c.minx and k.miny - 1e-6 <= c.miny
                    and k.maxx + 1e-6 >= c.maxx and k.maxy + 1e-6 >= c.maxy):
                contained = True
                break
        if not contained:
            kept.append(c)
    return kept


def sort_frames(frames):
    """排序：先上到下（中心 y 降序），后左到右（中心 x 升序）。"""
    return sorted(frames, key=lambda f: (-f.cy, f.cx))


def titleblock_region(frame, cfg=None):
    """标题栏候选区域，返回 (minx, miny, maxx, maxy)。

    2026-10-25 全情况整改：corner 支持右下角/底部/右上/左上/右侧竖条五种布局；
    region_expand_mm 外扩覆盖图框外红线区。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    wr = tb.get("default_width_ratio", 1.0)
    hr = tb.get("default_height_ratio", 0.2)
    wr = max(0.1, min(1.0, wr))
    hr = max(0.05, min(0.8, hr))
    expand = float(tb.get("region_expand_mm", 15))
    corner = tb.get("corner", CORNER_BOTTOM_RIGHT)
    if corner not in VALID_CORNERS:
        corner = CORNER_BOTTOM_RIGHT

    if corner == CORNER_BOTTOM:
        return (frame.minx - expand, frame.miny - expand,
                frame.maxx + expand, frame.miny + frame.height * hr)
    if corner == CORNER_TOP_RIGHT:
        return (frame.maxx - frame.width * wr - expand,
                frame.maxy - frame.height * hr - expand,
                frame.maxx + expand, frame.maxy + expand)
    if corner == CORNER_TOP_LEFT:
        return (frame.minx - expand,
                frame.maxy - frame.height * hr - expand,
                frame.minx + frame.width * wr + expand, frame.maxy + expand)
    if corner == CORNER_RIGHT:
        # 右侧竖条：宽度 wr * 图宽，高度整条
        return (frame.maxx - frame.width * wr - expand, frame.miny - expand,
                frame.maxx + expand, frame.maxy + expand)
    # bottom_right（默认）
    return (frame.maxx - frame.width * wr - expand, frame.miny - expand,
            frame.maxx + expand, frame.miny + frame.height * hr)


def top_header_region(frame, cfg=None):
    """C4：页面**顶部页眉**条带（图纸目录页/说明页的设计单位表通常在顶部）。

    右下角标题栏缺失时的保守回退。高度比例默认 0.14（页眉通常比底部标题栏矮），
    宽度横跨整幅，仅用于黑名单模式（只删公司名/人名/日期，不整删）。
    返回 (minx, miny, maxx, maxy)。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    hr = float(tb.get("top_header_height_ratio", 0.14))
    hr = max(0.05, min(0.35, hr))
    expand = float(tb.get("region_expand_mm", 15))
    return (frame.minx - expand, frame.maxy - frame.height * hr,
            frame.maxx + expand, frame.maxy + expand)


def detect_titleblock_region(frame, rects, cfg=None):
    """在右下角候选区锁定标题栏**真实小矩形**（2026-10-25 全情况整改）。

    替代固定 20% 高度的粗区域：从图框内的小矩形（线框聚类产物）中
    挑"最靠下且最靠右"的一个作为标题栏边界——标题栏通常在图框底部的
    右侧。找不到或面积不合理返回 None（调用方回退 titleblock_region）。

    返回 (minx, miny, maxx, maxy)。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    if not tb.get("use_real_region_detection", True):
        return None
    if not rects:
        return None
    fw, fh = frame.width, frame.height
    if fw <= 0 or fh <= 0:
        return None
    candidates = []
    for r in rects:
        minx, miny, maxx, maxy = r[0], r[1], r[2], r[3]
        w, h = maxx - minx, maxy - miny
        if w <= 1e-6 or h <= 1e-6:
            continue
        # 完全在图框内（含轻微外扩容差）
        if (minx < frame.minx - 5 or miny < frame.miny - 5
                or maxx > frame.maxx + 5 or maxy > frame.maxy + 5):
            continue
        area_ratio = (w * h) / (fw * fh)
        # 太大=整框/内容框，太小=碎线框
        if area_ratio > 0.45 or area_ratio < 0.015:
            continue
        # 长宽比不能太极端（标题栏横条 0.2~5，竖条另算）
        r_ = max(w, h) / min(w, h) if min(w, h) > 0 else 99
        if r_ > 12:
            continue
        # 越靠下、越靠右得分越高（y 向上，miny 越小越靠下）
        score = -miny * 1.0 + maxx * 0.001
        candidates.append((score, (minx, miny, maxx, maxy)))
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    return candidates[0][1]


def in_region(x, y, region):
    return region[0] - 1e-6 <= x <= region[2] + 1e-6 and region[1] - 1e-6 <= y <= region[3] + 1e-6


# C1：标题栏里常作为"字段标签"的保护词（标签与值常是两个分离文字实体）。
# 命中这些标签时，其右侧/下侧紧邻的"值"实体即使本身不含保护词也必须保留。
DEFAULT_FIELD_LABELS = (
    "工程名称", "工程名", "项目名称", "项目名", "子项名称", "子项",
    "图纸名称", "图名", "图号", "图纸编号", "图样代号", "图号编号",
    "设计阶段", "比例", "图别", "版次", "阶段", "专业",
    "设备名称", "设备型号", "规格型号", "型号", "规格",
)


def associate_label_values(targets, field_labels, block_labels, frame):
    """C1：标题栏"标签→值"几何关联（纯逻辑，不依赖 AutoCAD，可单测）。

    背景：标题栏中"工程名称"（标签）与"刚果（金）Manono…项目"（值）是两个独立
    文字实体；白名单按单实体判定时值不含保护词会被误删。本函数依据**同行、右侧、
    紧邻、遇下一个标签即止**的规则，把标签关联到的值标记为受保护。

    参数
    ----
    targets : list[dict]，每项含
        key（可哈希，通常是实体索引/对象 id）、
        norm（已去空白的文本）、
        minx/miny/maxx/maxy（包围盒世界坐标）
    field_labels : set[str]，已去空白的字段标签集合（如 {"图号","工程名称"}）
    block_labels : set[str]，已去空白；命中表示"下一个字段标签"，向右关联到此为止
    frame : Frame，用于按图幅归一化距离阈值

    返回
    ----
    set[key]：应作为"保护字段值"保留的实体 key 集合
    """
    protected = set()
    fw, fh = frame.width, frame.height
    if fw <= 0 or fh <= 0 or not targets:
        return protected

    def _is_field_label(norm):
        if not norm:
            return False
        for lab in field_labels:
            if lab and (norm == lab or norm.rstrip("：:") == lab
                        or norm.startswith(lab) and len(norm) <= len(lab) + 2):
                return True
        return False

    def _is_block(norm):
        if not norm:
            return False
        if _is_field_label(norm):
            return True
        return any(b and (norm == b or norm.startswith(b)) for b in block_labels)

    labels, others = [], []
    for t in targets:
        (labels if _is_field_label(t.get("norm")) else others).append(t)

    row_tol = max(fh * 0.012, 1.0)          # 同行容差（约一行字高）
    max_gap_x = fw * 0.5                      # 标签→值水平最大跨距（工程名较长）
    below_max_dy = fh * 0.06                  # 下方关联最大垂直距离
    overlap_gap = fw * 0.02                   # 允许标签与值轻微重叠/缝隙

    for lab in labels:
        lcx = (lab["minx"] + lab["maxx"]) / 2.0
        lcy = (lab["miny"] + lab["maxy"]) / 2.0
        lh = max(lab["maxy"] - lab["miny"], fh * 0.008)
        # 右侧同行候选
        right = []
        for v in others:
            if v["key"] in protected:
                # 已被别的标签保护的长值，仍可纳入本行
                pass
            vcy = (v["miny"] + v["maxy"]) / 2.0
            if abs(vcy - lcy) > max(row_tol, lh * 0.9):
                continue
            gap = v["minx"] - lab["maxx"]
            if gap < -overlap_gap:
                continue  # 整体在标签左边
            if gap > max_gap_x:
                continue
            right.append((v["minx"], v))
        right.sort(key=lambda z: z[0])
        for _x, v in right:
            if _is_block(v.get("norm")):
                break  # 遇到下一个字段标签，关联截止
            protected.add(v["key"])
        # 下方/同列候选（标题栏上下排布时取最近一个非标签值）
        below = []
        for v in others:
            if v["key"] in protected:
                continue
            vcx = (v["minx"] + v["maxx"]) / 2.0
            vcy = (v["miny"] + v["maxy"]) / 2.0
            dy = lcy - vcy  # y 轴向上，值在下方则 dy>0
            if 0 < dy <= max(lh * 1.2, below_max_dy):
                if abs(vcx - lcx) <= (lab["maxx"] - lab["minx"]) * 1.5 + fw * 0.03:
                    if not _is_block(v.get("norm")):
                        below.append((dy, v))
        if below:
            below.sort(key=lambda z: z[0])
            protected.add(below[0][1]["key"])
    return protected


def cluster(vals, tol):
    """一维坐标聚类（合并接近的值），返回代表值列表。"""
    vals = sorted(vals)
    out = []
    for v in vals:
        if out and abs(v - out[-1]) <= tol:
            out[-1] = (out[-1] + v) / 2.0
        else:
            out.append(v)
    return out


def build_rects_from_lines(h_lines, v_lines, tol=2.0, max_pairs=400):
    """由水平/垂直线段组合出矩形，返回 (minx, miny, maxx, maxy) 列表。"""
    if not h_lines or not v_lines:
        return []
    xs = cluster([v[0] for v in v_lines], tol)
    ys = cluster([h[0] for h in h_lines], tol)
    if len(xs) * len(ys) > 20000:
        return []
    rects = []
    pairs = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            x_lo, x_hi = min(xs[i], xs[j]), max(xs[i], xs[j])
            cover_ys = [h[0] for h in h_lines if h[1] <= x_lo + tol and h[2] >= x_hi - tol]
            if len(cover_ys) < 2:
                continue
            cys = cluster(cover_ys, tol)
            for a in range(len(cys)):
                for b in range(a + 1, len(cys)):
                    y_lo, y_hi = min(cys[a], cys[b]), max(cys[a], cys[b])
                    has_left = any(abs(v[0] - x_lo) <= tol and v[1] <= y_lo + tol and v[2] >= y_hi - tol for v in v_lines)
                    has_right = any(abs(v[0] - x_hi) <= tol and v[1] <= y_lo + tol and v[2] >= y_hi - tol for v in v_lines)
                    if has_left and has_right:
                        rects.append((x_lo, y_lo, x_hi, y_hi))
                        pairs += 1
                        if pairs > max_pairs:
                            return rects
    return rects
