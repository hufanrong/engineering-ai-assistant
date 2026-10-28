# -*- coding: utf-8 -*-
"""dwg_cleaner 标题栏几何识别纯逻辑测试（不依赖 AutoCAD，沙箱/CI 可直接跑）。

运行：
    cd tools && python -m dwg_cleaner.tests.test_titleblock

覆盖（对应清稿四查①「标题栏文字基本清空」的判定链路）：
- 标准图幅匹配（A1~A4 + 加长幅面 + 容差 + 非标否决）——图框识别入口
- fallback 边界（最小边/最大边/长宽比）
- Frame 属性 / is_portrait 竖版判断 / rotate_point 斜置坐标变换
- detect_frames：标准/嵌套去重/五元组 rotation/fallback 开关/退化矩形
- titleblock_region：五种 corner 布局 + 非法 corner 回退
- detect_titleblock_regions：真实小矩形候选过滤（面积比/极端长宽比/越界/topk/开关）
- in_region 边界含等号
- associate_label_values（C1）：protect/delete 两模式、stop 标签截止、N-04 紧邻跨距、下方关联
- find_cert_numbers（F-08/N-01）：证书号定位、X/Y 坐标排除、短号排除
- cluster 一维聚类、build_rects_from_lines 线段组矩形
- infer_titleblock_region_from_texts（F-05①）：文字簇反推标题栏区域
"""

import os
import sys

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from dwg_cleaner import titleblock as tb  # noqa: E402

_FAIL = 0
_PASS = 0


def check(name, cond, detail=""):
    global _FAIL, _PASS
    if cond:
        _PASS += 1
        print("  ✓ %s" % name)
    else:
        _FAIL += 1
        print("  ✗ %s  %s" % (name, detail))


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_standard_size_match():
    print("[标准图幅匹配]")
    check("A1 精确命中", tb.match_standard_size(841, 1189))
    check("A2 精确命中", tb.match_standard_size(841, 594))
    check("A3 精确命中", tb.match_standard_size(420, 594))
    check("A4 竖版命中（宽高互换）", tb.match_standard_size(297, 210))
    check("A2 加长 1/4 命中", tb.match_standard_size(594, 841 + 594 / 4.0))
    check("A1 加长 2/4 命中", tb.match_standard_size(841, 1189 + 2 * 841 / 4.0))
    check("容差 3mm 内命中", tb.match_standard_size(843, 1191))
    check("非标尺寸否决", not tb.match_standard_size(500, 700))
    check("零边否决", not tb.match_standard_size(0, 841))


def test_fallback_match():
    print("[fallback 边界]")
    check("非标但边界内命中", tb.match_fallback(200, 280))
    check("最小边不足否决", not tb.match_fallback(179, 250))
    check("最大边超限否决", not tb.match_fallback(300, 1400))
    check("长宽比过大否决", not tb.match_fallback(100, 290))
    check("长宽比临界命中", tb.match_fallback(180, 440))


def test_frame_and_portrait():
    print("[Frame / 竖版 / 旋转]")
    f = tb.Frame(0, 0, 420, 594)
    check("width 属性", approx(f.width, 420))
    check("height 属性", approx(f.height, 594))
    check("中心坐标", approx(f.cx, 210) and approx(f.cy, 297))
    check("A3 竖版判定", tb.is_portrait(f))
    check("A2 横版非竖版", not tb.is_portrait(tb.Frame(0, 0, 841, 594)))
    check("角度 0 旋转不变", tb.rotate_point(3, 4, 0, 0, 0.0) == (3, 4))
    x, y = tb.rotate_point(2, 0, 0, 0, 3.141592653589793 / 2)
    check("旋转 90° 变换", approx(x, 0, 1e-9) and approx(y, 2, 1e-9))


def test_detect_frames():
    print("[图框检测]")
    frames = tb.detect_frames([(0, 0, 594, 420)])
    check("单个 A3 横放图框", len(frames) == 1)
    nested = tb.detect_frames([(0, 0, 841, 1189), (10, 10, 430, 604)])
    check("嵌套图框保留外层", len(nested) == 1 and approx(nested[0].width, 841))
    rot = tb.detect_frames([(0, 0, 594, 420, 0.3)])
    check("五元组 rotation 保留", len(rot) == 1 and approx(rot[0].rotation, 0.3))
    check("非标+关闭 fallback 无图框",
          tb.detect_frames([(0, 0, 200, 280)], use_fallback=False) == [])
    check("非标+开启 fallback 兜底",
          len(tb.detect_frames([(0, 0, 200, 280)])) == 1)
    check("退化矩形忽略", tb.detect_frames([(0, 0, 0, 420)]) == [])
    two = tb.detect_frames([(0, 0, 594, 420), (700, 0, 1294, 420)])
    check("两个独立图框", len(two) == 2)


def test_titleblock_region_corners():
    print("[标题栏区域 corner 布局]")
    f = tb.Frame(0, 0, 841, 594)
    br = tb.titleblock_region(f, {"titleblock": {"corner": "bottom_right"}})
    check("右下角区域", approx(br[0], -15) and approx(br[3], 594 * 0.2, 1e-9))
    bo = tb.titleblock_region(f, {"titleblock": {"corner": "bottom"}})
    check("底部条带区域", approx(bo[0], -15) and approx(bo[2], 856))
    tr = tb.titleblock_region(f, {"titleblock": {"corner": "top_right"}})
    check("右上角区域", approx(tr[1], 594 - 594 * 0.2 - 15, 1e-9)
          and approx(tr[3], 609))
    tl = tb.titleblock_region(f, {"titleblock": {"corner": "top_left"}})
    check("左上角区域", approx(tl[0], -15) and approx(tl[3], 609))
    ri = tb.titleblock_region(f, {"titleblock": {"corner": "right"}})
    check("右侧竖条区域", approx(ri[0], -15) and approx(ri[1], -15))
    bad = tb.titleblock_region(f, {"titleblock": {"corner": "middle"}})
    check("非法 corner 回退右下角", bad == br)


def test_detect_titleblock_regions():
    print("[真实小矩形候选]")
    f = tb.Frame(0, 0, 594, 420)
    low_right = (434, 4, 584, 74)
    top_left = (10, 300, 160, 370)
    cands = tb.detect_titleblock_regions(f, [low_right, top_left])
    check("双候选返回且靠下靠右优先", cands and tuple(cands[0]) == low_right)
    check("超大候选剔除", tb.detect_titleblock_regions(f, [(0, 0, 500, 250)]) == [])
    check("微小候选剔除", tb.detect_titleblock_regions(f, [(10, 10, 20, 20)]) == [])
    check("极端长宽比剔除",
          tb.detect_titleblock_regions(f, [(100, 5, 550, 35)]) == [])
    check("越界候选剔除",
          tb.detect_titleblock_regions(f, [(-10, 5, 100, 75)]) == [])
    check("topk 限制",
          len(tb.detect_titleblock_regions(f, [low_right, top_left], topk=1)) == 1)
    check("开关关闭返回空",
          tb.detect_titleblock_regions(
              f, [low_right],
              {"titleblock": {"use_real_region_detection": False}}) == [])


def test_in_region():
    print("[区域内判定]")
    r = (0, 0, 10, 10)
    check("内部点", tb.in_region(5, 5, r))
    check("边界点含等号", tb.in_region(0, 0, r) and tb.in_region(10, 10, r))
    check("外部点否决", not tb.in_region(10.1, 5, r))


def _box(key, norm, minx, miny, maxx, maxy):
    return {"key": key, "norm": norm,
            "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def test_associate_label_values():
    print("[C1 标签→值几何关联]")
    f = tb.Frame(0, 0, 594, 420)

    targets = [
        _box(1, "工程名称", 100, 40, 130, 45),
        _box(2, "刚果（金）Manono项目", 135, 40, 220, 45),
        _box(3, "设计", 190, 40, 210, 45),
        _box(4, "远处无关文字", 215, 40, 260, 45),
    ]
    got = tb.associate_label_values(
        targets, {"工程名称"}, {"设计"}, f, mode="protect")
    check("protect：紧邻值保留", 2 in got)
    check("protect：block 标签截止", 4 not in got)

    below = tb.associate_label_values(
        [_box(1, "工程名称", 100, 60, 160, 65),
         _box(2, "紫金矿业项目", 100, 40, 145, 45)],
        {"工程名称"}, set(), f, mode="protect")
    check("protect：下方同列值关联", 2 in below)

    del_targets = [
        _box(1, "设计", 100, 40, 120, 45),
        _box(2, "张三", 122, 40, 140, 45),
        _box(3, "远距文字", 300, 40, 320, 45),
    ]
    got_del = tb.associate_label_values(
        del_targets, {"设计"}, {"工程名称"}, f,
        mode="delete", right_max_gap=8.0)
    check("delete：紧邻人名关联", 2 in got_del)
    check("delete：N-04 跨距收紧不误删", 3 not in got_del)


def test_find_cert_numbers():
    print("[F-08 证书号定位]")
    f = tb.Frame(0, 0, 594, 420)
    targets = [
        _box(1, "设计证书编号", 100, 100, 160, 105),
        _box(2, "A135036965", 100, 80, 145, 85),
        _box(3, "X9193900", 200, 80, 240, 85),
        _box(4, "A12345", 100, 60, 130, 65),
        _box(5, "123456789", 100, 40, 140, 45),
    ]
    got = tb.find_cert_numbers(targets, {"设计证书编号"}, f)
    check("正下方证书号命中", 2 in got)
    check("X 坐标排除", 3 not in got)
    check("短号排除", 4 not in got)
    check("超距纯数字排除", 5 not in got)


def test_cluster_and_rects():
    print("[聚类与线段组矩形]")
    check("一维聚类合并", tb.cluster([1, 1.5, 10], 2.0) == [1.25, 10])
    check("空输入聚类", tb.cluster([], 1.0) == [])
    v_lines = [(0, 0, 10), (10, 0, 10)]
    h_lines = [(0, 0, 10), (10, 0, 10)]
    rects = tb.build_rects_from_lines(h_lines, v_lines)
    check("线段组出矩形", rects and tuple(rects[0]) == (0, 0, 10, 10))
    check("缺线不组矩形", tb.build_rects_from_lines([], v_lines) == [])


def test_infer_region_from_texts():
    print("[F-05① 文字簇反推标题栏]")
    f = tb.Frame(0, 0, 594, 420)
    texts = [
        _box(1, "图号", 450, 60, 470, 65),
        _box(2, "图名", 450, 50, 470, 55),
        _box(3, "比例", 450, 40, 470, 45),
        _box(4, "GS-2026-01", 480, 60, 520, 65),
        _box(5, "平面布置图", 480, 50, 520, 55),
        _box(6, "1:100", 480, 40, 520, 45),
    ]
    got = tb.infer_titleblock_region_from_texts(
        f, texts, {"图号", "图名", "比例"}, {"图号", "图名", "比例"})
    check("文字簇反推出区域", got is not None)
    if got:
        region, strong_hits, _seed_hits = got
        check("强保护字段命中数达标", strong_hits >= 2)
        check("区域覆盖图号标签",
              tb.in_region(450, 62, region) and tb.in_region(520, 42, region))


def main():
    test_standard_size_match()
    test_fallback_match()
    test_frame_and_portrait()
    test_detect_frames()
    test_titleblock_region_corners()
    test_detect_titleblock_regions()
    test_in_region()
    test_associate_label_values()
    test_find_cert_numbers()
    test_cluster_and_rects()
    test_infer_region_from_texts()
    print("=" * 64)
    print("结果：通过 %d，失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
