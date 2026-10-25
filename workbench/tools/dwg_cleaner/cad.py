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

# PlotConfiguration 枚举（2026-10-25 实测修正：acWindow=4，3 是 acView）
PAPER_UNITS_MM = 1          # acMillimeters
PLOT_TYPE_WINDOW = 4        # acWindow（窗口打印；实测 3=acView 会导致「输入无效」）
PLOT_TYPE_EXTENTS = 1       # acExtents（范围打印，双保险回退路线）
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
        import time
        pythoncom.CoInitialize()
        self._com_initialized = True
        # 2026-10-25 实测（Bug9）：AutoCAD 冷启动期任意 COM 调用可能被拒
        # （-2147418111 被呼叫方拒绝接收呼叫），会话启动加就绪重试（5秒×6次）。
        app = None
        last_err = None
        for _ in range(6):
            try:
                app = win32com.client.Dispatch("AutoCAD.Application")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(5)
        if app is None:
            raise CadError("无法启动 AutoCAD（冷启动连接被拒，重试6次仍失败）：%s" % last_err)
        self.app = app
        # 版本容错：真实版本串可能是 "23.1s (LMS Tech)"，只取数字头
        try:
            m = re.match(r"(\d+(?:\.\d+)?)", str(self.app.Version))
            self.release = float(m.group(1)) if m else 0.0
        except Exception:
            self.release = 0.0
        # 2026-10-25 实测（Bug7）：不可见模式下「打印作业进度」对话框会僵死、
        # PlotToFile 永不返回 → 处理期间强制 Visible=True
        try:
            self.app.Visible = True
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
        """只读打开 DWG，返回文档对象。

        2026-10-25 实测（Bug8）：Documents.Open() 返回的对象动态绑定会损坏
        （Open.ModelSpace / ActiveDocument AttributeError）；改用 ActiveDocument，
        并以 FullName 精确匹配 Documents 集合兜底；大图打开后 COM 短暂失稳，
        60 秒重试窗口内持续重试。
        """
        import time
        full = os_path_abspath(path)
        doc = None
        last_err = None
        for _ in range(6):
            try:
                self.app.Documents.Open(full, readonly)
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(5)
                continue
            # 方式1：ActiveDocument（打开后自动激活）
            try:
                ad = self.app.ActiveDocument
                if ad is not None:
                    doc = ad
            except Exception:  # noqa: BLE001
                pass
            # 方式2：按 FullName 精确匹配
            if doc is None:
                try:
                    for j in range(self.app.Documents.Count):
                        try:
                            d = self.app.Documents.Item(j)
                            if str(d.FullName).lower() == full.lower():
                                doc = d
                                break
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    pass
            if doc is not None:
                break
            time.sleep(5)
        if doc is None:
            raise CadError("打开文件失败（COM 失稳，重试超时）：%s（原始错误：%s）" % (path, last_err))
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
        """按图框窗口范围输出单页 PDF。

        2026-10-25 实测重写（修复 9 项打印链路 Bug，真机 AutoCAD 2020 验证可用）：
        - Bug1  PlotConfigurations 是 Document 的属性（doc.Plot.PlotConfigurations 不存在）
        - Bug2  打印设备用 ConfigName（PlotDevice 不可设）
        - Bug3  PLOT_TYPE_WINDOW = 4（acWindow），3 是 acView
        - Bug4  必须先 SetWindowToPlot 存窗口 → 再切 PlotType=acWindow
        - Bug5  窗口坐标必须是 VARIANT(VT_ARRAY|VT_R8) 双精度数组
        - Bug6  BACKGROUNDPLOT=0 强制前台（否则 PlotToFile 返回 True 但 PDF 不生成）
        - Bug7  打印期间 app.Visible=True（不可见模式下进度框僵死）
        双保险：窗口打印失败 → 自动回退范围打印（acExtents，整图一页）。
        已验证不可行的路线（勿再试）：命令行 -PLOT + SendCommand 盲答序列、
        PlotViewName 命名视图路线。
        """
        import pythoncom
        plot_cfg = cfg.get("plot", {})
        device = plot_cfg.get("device", "DWG To PDF.pc3")
        style_sheet = plot_cfg.get("style_sheet", "monochrome.ctb")
        margin = plot_cfg.get("margin_mm", 10)

        try:
            doc.Plot.QuietErrorMode = True
        except Exception:
            pass

        # Bug6：后台打印静默失败 → 强制前台，打完恢复原值
        old_bg = None
        try:
            old_bg = doc.GetVariable("BACKGROUNDPLOT")
            doc.SetVariable("BACKGROUNDPLOT", 0)
        except Exception:
            pass

        try:
            cfgs = doc.PlotConfigurations  # Bug1：Document 属性
            name = "_TMP_CLEAN_CFG"
            try:
                old = cfgs.Item(name)
                old.Delete()
            except Exception:
                pass
            pc = cfgs.Add(name)
            try:
                pc.ConfigName = device  # Bug2：ConfigName
                pc.PaperUnits = PAPER_UNITS_MM
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
                # 双保险：窗口打印优先 → 失败回退范围打印
                last_err = None
                try:
                    # Bug4：先存窗口，再切 PlotType；Bug5：坐标用双精度 VARIANT 数组
                    lo = pythoncom.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                           [frame.minx, frame.miny])
                    hi = pythoncom.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                           [frame.maxx, frame.maxy])
                    pc.SetWindowToPlot(lo, hi)
                    pc.PlotType = PLOT_TYPE_WINDOW  # Bug3：acWindow=4
                    pc.PlotToFile(pdf_path)
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    try:
                        # 回退：范围打印（acExtents=1）——单图框效果等同，多图框整图一页
                        pc.PlotType = PLOT_TYPE_EXTENTS
                        pc.PlotToFile(pdf_path)
                    except Exception as e2:  # noqa: BLE001
                        raise CadError("PDF 打印失败（窗口/范围双路线均失败）：%s / %s" % (last_err, e2))
            finally:
                try:
                    pc.Delete()
                except Exception:
                    pass
        finally:
            if old_bg is not None:
                try:
                    doc.SetVariable("BACKGROUNDPLOT", old_bg)
                except Exception:
                    pass

    def _set_paper_size(self, pc, frame, margin):
        """选择与图框尺寸匹配的纸张（含边距）。

        2026-10-25 整改：匹配不到合适纸张时**不再抛异常中断**窗口打印，
        降级为默认纸张 + UseStandardScale=True; StandardScale=0（布满），
        窗口范围仍保证每框一页。
        """
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
        # 降级：默认纸张 + 布满（不抛异常）
        try:
            pc.UseStandardScale = True
            pc.StandardScale = 0
        except Exception:
            pass

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


def os_path_abspath(p):
    import os
    return os.path.abspath(p)


def os_remove(p):
    import os
    if os.path.exists(p):
        os.remove(p)
