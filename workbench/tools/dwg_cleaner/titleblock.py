# -*- coding: utf-8 -*-
"""图框检测、排序与标题栏区域定位。

纯几何逻辑，不依赖 AutoCAD。矩形统一用 (minx, miny, maxx, maxy) 表示，
坐标与世界坐标一致（y 轴向上）。
"""

STANDARD_SIZES_MM = [(841, 1189), (594, 841), (420, 594), (297, 420), (210, 297)]


class Frame:
    """一张图纸的矩形范围。"""

    __slots__ = ("minx", "miny", "maxx", "maxy")

    def __init__(self, minx, miny, maxx, maxy):
        self.minx, self.miny, self.maxx, self.maxy = minx, miny, maxx, maxy

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
        return "Frame(%.1f,%.1f,%.1f,%.1f)" % (self.minx, self.miny, self.maxx, self.maxy)


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

    返回 Frame 列表（未排序）。
    """
    cfg = cfg or {}
    fd = cfg.get("frame_detect", {})
    std = fd.get("standard_sizes_mm", STANDARD_SIZES_MM)
    tol = fd.get("tolerance_mm", 3)

    candidates = []
    for r in rects:
        minx, miny, maxx, maxy = r
        w, h = maxx - minx, maxy - miny
        if w <= 1e-9 or h <= 1e-9:
            continue
        if match_standard_size(w, h, std, tol):
            candidates.append(Frame(minx, miny, maxx, maxy))

    if not candidates and use_fallback:
        f_min = fd.get("fallback_min_side_mm", 180)
        f_max = fd.get("fallback_max_side_mm", 1300)
        r_min = fd.get("fallback_ratio_min", 0.4)
        r_max = fd.get("fallback_ratio_max", 2.5)
        for r in rects:
            minx, miny, maxx, maxy = r
            w, h = maxx - minx, maxy - miny
            if w <= 1e-9 or h <= 1e-9:
                continue
            if match_fallback(w, h, f_min, f_max, r_min, r_max):
                candidates.append(Frame(minx, miny, maxx, maxy))

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
    """标题栏候选区域：图框右下角一块矩形，返回 (minx, miny, maxx, maxy)。

    默认取图框底部整条（宽 100%）、高度 20%；比例可在配置中调整。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    wr = tb.get("default_width_ratio", 1.0)
    hr = tb.get("default_height_ratio", 0.2)
    wr = max(0.1, min(1.0, wr))
    hr = max(0.05, min(0.8, hr))
    minx = frame.maxx - frame.width * wr
    maxy = frame.miny + frame.height * hr
    return (minx, frame.miny, frame.maxx, maxy)


def in_region(x, y, region):
    return region[0] - 1e-6 <= x <= region[2] + 1e-6 and region[1] - 1e-6 <= y <= region[3] + 1e-6


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
    """由水平/垂直线段组合出矩形，返回 (minx, miny, maxx, maxy) 列表。

    h_lines: [(y, x1, x2), ...]
    v_lines: [(x, y1, y2), ...]
    """
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
            # 覆盖 [x_lo, x_hi] 的水平线所在 y 值
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
