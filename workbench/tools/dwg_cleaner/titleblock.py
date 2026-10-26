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


def detect_titleblock_regions(frame, rects, cfg=None, topk=8):
    """在右下角候选区找出标题栏**真实小矩形**候选列表（F-05②，2026-10-26）。

    v0.1.156 仅返回 top1，一旦 top1 是图签表格里的一个 40×24 小格（区域内文字数 0），
    保护词验证失败就整体放弃。本函数改为返回按"靠下、靠右"评分排序的 topk 候选，
    由调用方逐个验保护词，救回 top1 误判。

    返回 [(minx,miny,maxx,maxy), ...]（已按评分降序），无候选返回 []。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    if not tb.get("use_real_region_detection", True):
        return []
    if not rects:
        return []
    fw, fh = frame.width, frame.height
    if fw <= 0 or fh <= 0:
        return []
    ratio_lo = float(tb.get("region_area_ratio_min", 0.015))
    ratio_hi = float(tb.get("region_area_ratio_max", 0.45))
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
        if area_ratio > ratio_hi or area_ratio < ratio_lo:
            continue
        # 长宽比不能太极端（标题栏横条 0.2~5，竖条另算）
        r_ = max(w, h) / min(w, h) if min(w, h) > 0 else 99
        if r_ > 12:
            continue
        # 越靠下、越靠右得分越高（y 向上，miny 越小越靠下）
        score = -miny * 1.0 + maxx * 0.001
        candidates.append((score, (minx, miny, maxx, maxy)))
    candidates.sort(key=lambda c: -c[0])
    return [c[1] for c in candidates[:topk]]


def detect_titleblock_region(frame, rects, cfg=None):
    """单候选（向后兼容）：返回评分最高的候选，无则 None。"""
    cands = detect_titleblock_regions(frame, rects, cfg)
    return cands[0] if cands else None


def infer_titleblock_region_from_texts(frame, text_boxes, seed_labels, strong_labels, cfg=None):
    """F-05①：由标题栏**文字簇**反推真实区域（线条表格标题栏兜底，首选方案）。

    本项目标题栏是用直线绘制的表格，没有闭合小矩形，detect_titleblock_regions 锁不住
    区域。但标题栏内"图号/工程名称/图名/比例/设计/审核/审定/日期/证书编号"等标签文字
    是稳定特征：在右下角象限把这些文字按包围盒连通聚类，取"含强保护字段标签最多"的
    簇，其包围盒外扩即为标题栏区域。

    参数
    ----
    text_boxes : list[dict]，每项含 norm（已归一化/剥格式码）、minx/miny/maxx/maxy
    seed_labels : set[str]，全部标题栏标签（强保护+人名+日期+证书，归一化）
    strong_labels : set[str]，强保护字段标签（图号/工程名/图名/比例…），用于确认
    返回
    ----
    (region, strong_hits, seed_hits) 或 None。region 已外扩并夹取到图框内。
    """
    cfg = cfg or {}
    tb = cfg.get("titleblock", {})
    if not tb.get("infer_region_from_texts", True):
        return None
    fw, fh = frame.width, frame.height
    if fw <= 0 or fh <= 0:
        return None
    x_ratio = float(tb.get("infer_right_ratio", 0.10))     # 右侧 90% 起（兼容横跨底部大图签）
    y_ratio = float(tb.get("infer_bottom_ratio", 0.45))    # 底部 45%
    gap_x = fw * float(tb.get("infer_gap_x_ratio", 0.09))
    gap_y = fh * float(tb.get("infer_gap_y_ratio", 0.030))
    row_tol = max(fh * 0.014, 1.5)
    col_tol = fw * 0.02
    min_strong = int(tb.get("infer_min_strong", 2))
    expand = float(tb.get("region_expand_mm", 15))

    def _hit(norm, labels):
        if not norm:
            return False
        for lab in labels:
            if lab and (norm == lab or norm.rstrip("：:") == lab
                        or norm.startswith(lab) and len(norm) <= len(lab) + 2):
                return True
        return False

    # 1) 右下象限文字
    cand = []
    for t in text_boxes:
        cx = (t["minx"] + t["maxx"]) / 2.0
        cy = (t["miny"] + t["maxy"]) / 2.0
        if cx < frame.minx + fw * x_ratio:
            continue
        if cy > frame.miny + fh * y_ratio:
            continue
        cand.append(t)
    if len(cand) < 3:
        return None

    # 2) 并查集连通聚类：同行（垂直重叠）水平近邻 / 同列（水平重叠）垂直近邻
    n = len(cand)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        a = cand[i]
        for j in range(i + 1, n):
            b = cand[j]
            dx = max(0.0, max(a["minx"], b["minx"]) - min(a["maxx"], b["maxx"]))
            dy = max(0.0, max(a["miny"], b["miny"]) - min(a["maxy"], b["maxy"]))
            v_overlap = min(a["maxy"], b["maxy"]) - max(a["miny"], b["miny"])
            h_overlap = min(a["maxx"], b["maxx"]) - max(a["minx"], b["minx"])
            if v_overlap >= -row_tol and dx <= gap_x:
                union(i, j)          # 同一行
            elif h_overlap >= -col_tol and dy <= gap_y:
                union(i, j)          # 同一列上下相邻

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    # 3) 选含强保护字段标签最多（≥min_strong）的簇；并列取种子多、面积大
    best = None
    for _root, idxs in clusters.items():
        members = [cand[i] for i in idxs]
        strong = sum(1 for m in members if _hit(m["norm"], strong_labels))
        seeds = sum(1 for m in members if _hit(m["norm"], seed_labels))
        if strong < min_strong:
            continue
        area = ((max(m["maxx"] for m in members) - min(m["minx"] for m in members))
                * (max(m["maxy"] for m in members) - min(m["miny"] for m in members)))
        key = (strong, seeds, area)
        if best is None or key > best[0]:
            best = (key, members)
    if best is None:
        return None
    members = best[1]
    minx = min(m["minx"] for m in members) - expand
    miny = min(m["miny"] for m in members) - expand
    maxx = max(m["maxx"] for m in members) + expand
    maxy = max(m["maxy"] for m in members) + expand
    # 夹取到图框内（外扩不得越过图框，避免吞进相邻图框/坐标）
    minx = max(minx, frame.minx - 2)
    miny = max(miny, frame.miny - 2)
    maxx = min(maxx, frame.maxx + 2)
    maxy = min(maxy, frame.maxy + 2)
    region = (minx, miny, maxx, maxy)
    return region, best[0][0], best[0][1]


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


def associate_label_values(targets, field_labels, block_labels, frame, mode="protect"):
    """标题栏"标签→值"几何关联（纯逻辑，不依赖 AutoCAD，可单测）。

    背景：标题栏中"工程名称"（标签）与"刚果（金）Manono…项目"（值）是两个独立
    文字实体；白名单按单实体判定时值不含保护词会被误删。本函数依据**同行、右侧、
    紧邻、遇下一个标签即止**的规则，把标签关联到的值标记出来。

    mode（F-01，2026-10-26）：
      protect（默认）：field_labels=保护字段标签（图号/工程名/图名…），关联到的值
                      标记为"保留"；block_labels=人名/日期标签，向右遇到即止。
      delete        ：field_labels=删除标签（设计/审核/审定/标图/日期/证书编号…），
                      关联到的值（人名/日期/证书号）标记为"删除"；block_labels 应传
                      保护字段标签，避免误删到相邻字段值。两种模式几何完全相同，
                      区别只在调用方传入的标签集与对结果的处理。

    参数
    ----
    targets : list[dict]，每项含
        key（可哈希，通常是实体索引/对象 id）、
        norm（已去空白、已剥 MText 格式码的可见文本）、
        minx/miny/maxx/maxy（包围盒世界坐标）
    field_labels : set[str]，已去空白的"种子标签"集合
    block_labels : set[str]，已去空白；命中表示"下一个字段标签"，向右关联到此为止
    frame : Frame，用于按图幅归一化距离阈值

    返回
    ----
    set[key]：与种子标签关联到的值实体 key 集合
    """
    return associate_values(targets, field_labels, block_labels, frame)


def associate_values(targets, seed_labels, stop_labels, frame):
    """通用"标签→值"几何关联（associate_label_values 的实现，protect/delete 共用）。

    规则：对每个种子标签，取其**同行右侧紧邻**的值（水平间隙内、遇下一个标签即止），
    并兜底取**下方/同列**最近的一个非标签值。
    """
    result = set()
    fw, fh = frame.width, frame.height
    if fw <= 0 or fh <= 0 or not targets:
        return result

    def _is_seed(norm):
        if not norm:
            return False
        for lab in seed_labels:
            if lab and (norm == lab or norm.rstrip("：:") == lab
                        or norm.startswith(lab) and len(norm) <= len(lab) + 2):
                return True
        return False

    def _is_stop(norm):
        if not norm:
            return False
        if _is_seed(norm):
            return True
        return any(b and (norm == b or norm.startswith(b)) for b in stop_labels)

    labels, others = [], []
    for t in targets:
        (labels if _is_seed(t.get("norm")) else others).append(t)

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
            if _is_stop(v.get("norm")):
                break  # 遇到下一个字段标签，关联截止
            result.add(v["key"])
        # 下方/同列候选（标题栏上下排布时取最近一个非标签值）
        below = []
        for v in others:
            if v["key"] in result:
                continue
            vcx = (v["minx"] + v["maxx"]) / 2.0
            vcy = (v["miny"] + v["maxy"]) / 2.0
            dy = lcy - vcy  # y 轴向上，值在下方则 dy>0
            if 0 < dy <= max(lh * 1.2, below_max_dy):
                if abs(vcx - lcx) <= (lab["maxx"] - lab["minx"]) * 1.5 + fw * 0.03:
                    if not _is_stop(v.get("norm")):
                        below.append((dy, v))
        if below:
            below.sort(key=lambda z: z[0])
            result.add(below[0][1]["key"])
    return result


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
