# -*- coding: utf-8 -*-
"""AutoCAD COM/ActiveX 封装层。

仅在 Windows + 已安装 AutoCAD 的环境可用；win32com 采用函数内延迟导入，
保证在无 AutoCAD 的机器上 import 本包不报错（核心逻辑仍可测试）。

实体类型（ObjectName）约定：
- AcDbText / AcDbMText : 单行 / 多行文字
- AcDbAttribute       : 块属性引用
- AcDbBlockReference  : 块引用（INSERT）
- AcDbPolyline        : 轻量多段线（含 RECTANG 生成的图框）
- AcDbLine            : 直线
- AcDbProxyEntity     : 代理实体（天正等第三方对象）
"""

import re

# SaveAs 格式枚举（AutoCAD 2018 DWG = 64；低版本 AutoCAD 无法保存高版本格式）
AC_2018_DWG = 64   # R2018+
AC_2013_DWG = 61   # R2013-R2017
AC_2010_DWG = 60   # R2010-R2012
AC_2007_DWG = 57   # R2007-R2009
AC_2004_DWG = 51   # R2004-R2006
AC_2000_DWG = 49   # R2000-R2003


def saveas_format_for_release(release: float) -> int:
    """按 AutoCAD 内部版本号（如 24.0=2020）选择可保存的最高通用格式，
    保证任意版本 AutoCAD 都能另存清稿副本。"""
    if release >= 23.0:
        return AC_2018_DWG
    if release >= 19.1:
        return AC_2013_DWG
    if release >= 18.1:
        return AC_2010_DWG
    if release >= 17.1:
        return AC_2007_DWG
    if release >= 16.0:
        return AC_2004_DWG
    return AC_2000_DWG

# PlotConfiguration 枚举
PAPER_UNITS_MM = 1          # acMillimeters
PLOT_TYPE_WINDOW = 3        # acWindow
ROT_0 = 0                   # ac0degrees
ROT_90 = 1                  # ac90degrees


class CadError(Exception):
    """AutoCAD 相关错误。"""


class CadSession:
    """AutoCAD 会话上下文管理器：进入时启动/连接 CAD，退出时关闭所有文档并退出。"""

    def __init__(self, visible=False):
        self.visible = visible
        self.app = None
        self._doc = None
        self._com_initialized = False

    def __enter__(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        self._com_initialized = True
        try:
            self.app = win32com.client.Dispatch("AutoCAD.Application")
        except Exception as e:
            raise CadError("无法启动 AutoCAD，请确认本机已安装 AutoCAD 并能正常打开。原始错误：%s" % e)
        # v1.1：读取实际 AutoCAD 版本（任意版本兼容），用于选择可保存的 DWG 格式
        try:
            self.release = float(str(self.app.Version))
        except Exception:
            self.release = 0.0
        try:
            self.app.Visible = bool(self.visible)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._doc is not None:
                try:
                    self._doc.Close(False)
                except Exception:
                    pass
                self._doc = None
        finally:
            try:
                if self.app is not None:
                    self.app.Quit()
            except Exception:
                pass
            self.app = None
            if self._com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        return False

    # ---------- 文档 ----------

    def open_document(self, path, readonly=True):
        """只读打开 DWG，返回文档对象。"""
        try:
            doc = self.app.Documents.Open(path, readonly)
        except Exception as e:
            raise CadError("打开文件失败（可能被其他程序占用或文件损坏）：%s" % path) from e
        self._doc = doc
        try:
            doc.SetVariable("FILEDIA", 0)
        except Exception:
            pass
        return doc

    def save_as(self, doc, path):
        """另存为清稿副本。v1.1：按当前 AutoCAD 版本选择可保存的最高通用格式
        （2018+ 存 2018 格式；低版本存对应格式，保证其他机器可打开）。"""
        if os_path_exists(path):
            os_remove(path)
        fmt = saveas_format_for_release(self.release)
        try:
            doc.SaveAs(path, fmt)
        except Exception:
            try:
                doc.SaveAs(path)
            except Exception:
                pass

    def close_document(self, doc, save=False):
        try:
            doc.Close(bool(save))
        except Exception:
            pass
        if doc is self._doc:
            self._doc = None

    # ---------- 实体遍历 ----------

    def iter_entities(self, space):
        """安全遍历实体集合（允许在收集完成后统一删除）。"""
        i = 0
        while i < space.Count:
            yield space.Item(i)
            i += 1

    # ---------- 实体几何 ----------

    def get_bounds(self, ent):
        """返回 (minx, miny, maxx, maxy)，失败返回 None。"""
        try:
            mn, mx = ent.GetBoundingBox()
            mn = tuple(mn)
            mx = tuple(mx)
            return (mn[0], mn[1], mx[0], mx[1])
        except Exception:
            return None

    def get_insertion(self, ent):
        """返回 (x, y)，失败返回 None。"""
        try:
            p = tuple(ent.InsertionPoint)
            return (p[0], p[1])
        except Exception:
            return None

    def get_polyline_rect(self, ent):
        """从闭合多段线中提取矩形边界；非矩形返回 None。"""
        name = ent.ObjectName
        if name not in ("AcDbPolyline", "AcDb2dPolyline"):
            return None
        try:
            closed = bool(ent.Closed)
        except Exception:
            closed = True
        if not closed:
            return None
        try:
            coords = list(ent.Coordinates)
        except Exception:
            return None
        if len(coords) != 8:  # 4 个顶点
            return None
        pts = [(coords[i], coords[i + 1]) for i in range(0, 8, 2)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        tol = max(maxx - minx, maxy - miny) * 0.005 + 1e-6
        for (x, y) in pts:
            near_x = abs(x - minx) <= tol or abs(x - maxx) <= tol
            near_y = abs(y - miny) <= tol or abs(y - maxy) <= tol
            if not (near_x and near_y):
                return None  # 非轴对齐矩形（如斜置图框），不处理
        return (minx, miny, maxx, maxy)

    def collect_lines(self, space, tolerance=1e-3):
        """收集水平线与竖线，返回 (h_lines, v_lines)。"""
        h_lines, v_lines = [], []
        for ent in self.iter_entities(space):
            if ent.ObjectName != "AcDbLine":
                continue
            try:
                s = tuple(ent.StartPoint)
                e = tuple(ent.EndPoint)
            except Exception:
                continue
            dx, dy = e[0] - s[0], e[1] - s[1]
            if abs(dy) <= tolerance and abs(dx) > tolerance:
                h_lines.append((s[1], min(s[0], e[0]), max(s[0], e[0])))
            elif abs(dx) <= tolerance and abs(dy) > tolerance:
                v_lines.append((s[0], min(s[1], e[1]), max(s[1], e[1])))
        return h_lines, v_lines

    # ---------- 块操作 ----------

    def explode_ref(self, ent):
        """炸开块引用并删除原引用，返回炸出的实体列表；失败返回 []。"""
        try:
            arr = ent.Explode()
            ent.Delete()
            if arr is None:
                return []
            return list(arr)
        except Exception:
            return []

    def is_proxy(self, ent):
        try:
            return ent.ObjectName == "AcDbProxyEntity"
        except Exception:
            return True

    # ---------- 文字 ----------

    TEXT_NAMES = ("AcDbText", "AcDbMText", "AcDbAttribute")

    def get_text(self, ent):
        try:
            if ent.ObjectName in self.TEXT_NAMES:
                return str(ent.TextString or "")
        except Exception:
            pass
        return None

    def set_text(self, ent, new_text):
        ent.TextString = new_text

    def delete_entity(self, ent):
        ent.Delete()

    # ---------- 打印 ----------

    def plot_frame(self, doc, frame, pdf_path, cfg):
        """按图框窗口范围输出单页 PDF。"""
        plot_cfg = cfg.get("plot", {})
        device = plot_cfg.get("device", "DWG To PDF.pc3")
        style_sheet = plot_cfg.get("style_sheet", "monochrome.ctb")
        margin = plot_cfg.get("margin_mm", 10)

        try:
            doc.Plot.QuietErrorMode = True
        except Exception:
            pass

        cfgs = doc.Plot.PlotConfigurations
        name = "_TMP_CLEAN_CFG"
        try:
            old = cfgs.Item(name)
            old.Delete()
        except Exception:
            pass
        pc = cfgs.Add(name)
        try:
            pc.PlotDevice = device
            pc.PaperUnits = PAPER_UNITS_MM
            pc.PlotType = PLOT_TYPE_WINDOW
            pc.UseStandardScale = False
            pc.SetCustomScale(1.0, 1.0)  # 1:1
            pc.CenterPlot = True
            pc.PlotRotation = ROT_0 if frame.width >= frame.height else ROT_90
            if style_sheet:
                try:
                    pc.StyleSheet = style_sheet
                except Exception:
                    pass
            self._set_paper_size(pc, frame, margin)
            pc.SetWindowToPlot(frame.minx, frame.miny, frame.maxx, frame.maxy)
            pc.PlotToFile(pdf_path)
        finally:
            try:
                pc.Delete()
            except Exception:
                pass

    def _set_paper_size(self, pc, frame, margin):
        """选择与图框尺寸匹配的纸张（含边距）。"""
        need_w = frame.width + 2 * margin
        need_h = frame.height + 2 * margin
        target = (min(need_w, need_h), max(need_w, need_h))
        try:
            pc.RefreshPlotDeviceInfo()
        except Exception:
            pass
        names = []
        try:
            names = list(pc.GetCanonicalMediaNames())
        except Exception:
            names = []
        chosen = None
        best_diff = None
        for n in names:
            m = re.search(r"\(([\d.]+)\s*x\s*([\d.]+)\s*MM\)", n, re.IGNORECASE)
            if not m:
                continue
            w, h = float(m.group(1)), float(m.group(2))
            if abs(min(w, h) - target[0]) <= 5 and abs(max(w, h) - target[1]) <= 5:
                chosen = n
                break
            # 记录最接近的纸张作为回退
            diff = abs(min(w, h) - target[0]) + abs(max(w, h) - target[1])
            if best_diff is None or diff < best_diff:
                best_diff = diff
                chosen = n
        if chosen:
            try:
                pc.CanonicalMediaName = chosen
                return
            except Exception:
                pass
        raise CadError("未找到与图幅匹配的 PDF 纸张（图框 %.0fx%.0fmm）" % (frame.width, frame.height))

    # ---------- 模型空间范围 ----------

    def space_extents(self, space):
        xs, ys = [], []
        for ent in self.iter_entities(space):
            b = self.get_bounds(ent)
            if b:
                xs.extend([b[0], b[2]])
                ys.extend([b[1], b[3]])
        if not xs:
            return (0.0, 0.0, 1.0, 1.0)
        return (min(xs), min(ys), max(xs), max(ys))


# 兼容 Windows 路径操作（避免顶层 import os 干扰模块语义）
def os_path_exists(p):
    import os
    return os.path.exists(p)


def os_remove(p):
    import os
    if os.path.exists(p):
        os.remove(p)
