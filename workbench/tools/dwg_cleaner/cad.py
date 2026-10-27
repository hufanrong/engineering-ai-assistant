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

P-09（2026-10-26）：AutoCAD 忙（模态/重生成）时拒绝 COM 调用
com_error(-2147418111, RPC_E_CALL_REJECTED)；统一封装 _retry_com 忙等待重试。
P-11（2026-10-26）：会话用 DispatchEx 独立实例（不复用用户手开/僵尸实例），
退出时 Quit 后轮询进程真正退出（≤10s），未退出按 HWND→PID 强制结束。
"""

import re

# P-09：RPC_E_CALL_REJECTED（AutoCAD 忙时拒绝 COM 调用）
_COM_REJECTED_HRESULT = -2147418111
# P-09：忙等待重试默认参数（40 次 × 0.25s = 10s，覆盖重生成/模态窗口）
_COM_RETRY_TRIES = 40
_COM_RETRY_WAIT = 0.25


def _is_com_rejected(e):
    """是否为"呼叫被拒绝"（AutoCAD 忙）类 COM 错误。"""
    hres = getattr(e, "hresult", None)
    if hres == _COM_REJECTED_HRESULT:
        return True
    s = str(e)
    return any(k in s for k in ("被呼叫方拒绝接收呼叫", "呼叫被拒绝", "RPC_E_CALL_REJECTED",
                                "0x80010001"))


def sys_platform_startswith_win():
    """是否 Windows（P-11 进程管理用；避免顶层 import sys 干扰模块语义）。"""
    import sys
    return sys.platform.startswith("win")


def _retry_com(fn, tries=_COM_RETRY_TRIES, wait=_COM_RETRY_WAIT):
    """P-09：调用 fn()，遇"呼叫被拒绝"忙等待重试；其它异常立即上抛。

    用于 AutoCAD 忙（模态/重生成）时被拒的 COM 调用：iter_entities（Count/Item）、
    SaveAs 等高频/关键调用点。返回 fn() 结果；重试耗尽抛出最后一次异常。
    """
    import time
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_com_rejected(e):
                raise
            time.sleep(wait)
    raise last

# SaveAs 格式枚举（AutoCAD 2018 DWG = 64；低版本 AutoCAD 无法保存高版本格式）
AC_2018_DWG = 64   # R2018+
AC_2013_DWG = 61   # R2013-R2017
AC_2010_DWG = 60   # R2010-R2012
AC_2007_DWG = 57   # R2007-R2009
AC_2004_DWG = 51   # R2004-R2006
AC_2000_DWG = 49   # R2000-R2003
# DXF 格式 = 对应 DWG 格式 + 1（ac2018_dxf=65 / ac2013_dxf=62）


def saveas_format_for_release(release: float, dxf: bool = False) -> int:
    """按 AutoCAD 内部版本号（如 23.1=2020）选择可保存的最高通用格式，
    保证任意版本 AutoCAD 都能另存清稿副本。dxf=True 时返回对应 DXF 格式
    （低版本统一存 2013 DXF，兼容性最好）。"""
    if release >= 23.0:
        fmt = AC_2018_DWG
    elif release >= 19.1:
        fmt = AC_2013_DWG
    elif release >= 18.1:
        fmt = AC_2010_DWG
    elif release >= 17.1:
        fmt = AC_2007_DWG
    elif release >= 16.0:
        fmt = AC_2004_DWG
    else:
        fmt = AC_2000_DWG
    if dxf:
        return fmt + 1 if fmt >= AC_2013_DWG else AC_2013_DWG + 1
    return fmt

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
        # P-11：会话前已存在的 acad.exe PID 白名单（退出强杀时排除，防误杀用户实例）
        self._baseline_acad_pids = set()
        # R2：打印链路中被容错跳过的属性设置（不静默，处理后透出 notes）
        self._plot_warnings = []

    def drain_plot_warnings(self):
        """取出并清空打印阶段收集的告警（R2：禁止静默吞异常）。"""
        ws = self._plot_warnings
        self._plot_warnings = []
        return ws

    def __enter__(self):
        import pythoncom
        import win32com.client
        import time
        pythoncom.CoInitialize()
        self._com_initialized = True
        # P-11（2026-10-26）：会话开始前已存在的 acad.exe PID 记为基线白名单——
        # 退出时只强杀**本次启动的新实例**，绝不误杀用户手动打开的 AutoCAD。
        self._baseline_acad_pids = self._list_acad_pids()
        # P-11（2026-10-26）：DispatchEx 启动**独立实例**——不复用用户手开的 AutoCAD，
        # 也绝不复用崩溃遗留的半死实例（其 Documents.Open 代理失效 <unknown>.Open，
        # 会导致后续所有运行全部失败）。
        app = None
        last_err = None
        for _ in range(6):
            try:
                app = win32com.client.DispatchEx("AutoCAD.Application")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(5)
        if app is None:
            raise CadError("无法启动独立 AutoCAD 实例（DispatchEx 冷启动被拒，重试6次仍失败）：%s"
                           % last_err)
        # P-11：就绪探测——冷启动期 COM 动态绑定短暂失效，实际访问一次才算就绪
        ready = False
        for _ in range(12):
            try:
                _ = app.Documents.Count
                ready = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(2)
        if not ready:
            raise CadError("独立 AutoCAD 实例未就绪（COM 绑定失稳，重试12次仍失败）")
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
            # P-11：Quit 不等于进程退出——轮询进程是否真正消失（≤10s），
            # 未退出按基线白名单 + HWND→PID 双路定位，强制结束本次启动的
            # 实例，避免残留半死实例污染下次运行。
            self._ensure_process_exit()
            self.app = None
            if self._com_initialized:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        return False

    def _ensure_process_exit(self, timeout=10.0):
        """P-11：Quit 后轮询 AutoCAD 进程真正退出；未退出则 taskkill 强制结束。

        v0.1.163（真机 P-11 未生效）：v0.1.162 只按 app.HWND→PID 定位，HWND
        属性读取失败即返回 None、跳过强杀 → acad.exe 残留。本版双路兜底：
        ① HWND→PID；② 枚举全部 acad.exe，剔除会话开始前的基线白名单，
        剩余即本次启动的实例（进程对象不可达时也能定位）。
        """
        import time
        base = set(getattr(self, "_baseline_acad_pids", None) or [])
        pids = set(self._list_acad_pids())
        hwnd_pid = self._app_pid()
        if hwnd_pid:
            pids.add(hwnd_pid)
        mine = pids - base
        if not mine:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            alive = [p for p in mine if self._pid_alive(p)]
            if not alive:
                return
            time.sleep(0.5)
        # 超时仍存活 → 强制结束（Windows taskkill /F /T；Linux kill -9）
        try:
            import subprocess
            for pid in alive:
                if sys_platform_startswith_win():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=15)
                else:
                    subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001
            pass

    def _list_acad_pids(self):
        """枚举当前所有 acad.exe 进程 PID（Windows tasklist；其他平台返回空）。"""
        if not sys_platform_startswith_win():
            return set()
        try:
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq acad.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="gbk", errors="replace",
                timeout=15).stdout or ""
            pids = set()
            for line in out.splitlines():
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2 and parts[1].strip().isdigit():
                    pids.add(int(parts[1].strip()))
            return pids
        except Exception:  # noqa: BLE001
            return set()

    def _app_pid(self):
        """按 app.HWND 定位 AutoCAD 进程 PID（Windows）；失败返回 None。"""
        if not sys_platform_startswith_win():
            return None
        try:
            import win32gui
            hwnd = int(self.app.HWND)
            _tid, pid = win32gui.GetWindowThreadProcessId(hwnd)
            return int(pid)
        except Exception:  # noqa: BLE001
            return None

    def _pid_alive(self, pid):
        """进程是否存活（Windows tasklist 精确匹配；Linux os.kill 探测）。"""
        try:
            if sys_platform_startswith_win():
                import subprocess
                out = subprocess.run(
                    ["tasklist", "/FI", "PID eq %d" % pid],
                    capture_output=True, text=True, encoding="gbk", errors="replace",
                    timeout=15).stdout
                return str(pid) in (out or "")
            import os
            os.kill(pid, 0)
            return True
        except Exception:  # noqa: BLE001
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

        def _usable(d):
            """2026-10-26 加固：对象非空 ≠ 可用。

            大图打开后 COM 动态绑定会短暂损坏，此时 Documents.Item / ActiveDocument
            仍返回对象，但读属性报 AttributeError: <unknown>.ModelSpace 或
            AutoCAD.Application.ActiveDocument。必须实际访问一次才算等到。
            """
            if d is None:
                return False
            try:
                _ = str(d.Name)
            except Exception:  # noqa: BLE001
                return False
            try:
                _ = d.ModelSpace.Count
            except Exception:  # noqa: BLE001
                return False
            return True

        def _candidates():
            out = []
            # 方式1：ActiveDocument（打开后自动激活）
            try:
                ad = self.app.ActiveDocument
                if ad is not None:
                    out.append(ad)
            except Exception:  # noqa: BLE001
                pass
            # 方式2：按 FullName 精确匹配
            try:
                cnt = self.app.Documents.Count
            except Exception:  # noqa: BLE001
                cnt = 0
            for j in range(cnt):
                try:
                    d = self.app.Documents.Item(j)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    if str(d.FullName).replace("/", "\\").lower() == \
                            full.replace("/", "\\").lower():
                        out.append(d)
                except Exception:  # noqa: BLE001
                    continue
            return out

        # 第一步：只打开一次（避免重复 Open 造成多份文档占用内存）
        opened = False
        for _ in range(6):
            try:
                self.app.Documents.Open(full, readonly)
                opened = True
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(5)
        # 第二步：轮询等待文档对象真正可用（大图可达数十秒）
        if opened:
            deadline = time.time() + 90
            while time.time() < deadline and doc is None:
                for cand in _candidates():
                    if _usable(cand):
                        doc = cand
                        break
                if doc is None:
                    time.sleep(3)
        if doc is None:
            # 加密图纸：Open 报错含 password/口令 → 明确识别，不弹窗挂死
            err = str(last_err or "")
            if any(k in err.lower() for k in ("password", "口令", "密码")):
                raise CadError("文件受密码保护（加密图纸），无法自动打开。请在 AutoCAD 中手动打开并移除密码后重试：%s" % path)
            raise CadError("打开文件失败（COM 失稳，重试超时）：%s（原始错误：%s）" % (path, last_err))
        self._doc = doc
        try:
            doc.SetVariable("FILEDIA", 0)
        except Exception:
            pass
        return doc

    def save_as(self, doc, path):
        """另存为清稿副本。v1.1：按当前 AutoCAD 版本选择可保存的最高通用格式。
        v0.1.156：按输入扩展名匹配保存格式（.dxf 存 DXF，.dwg 存 DWG）。
        v0.1.159（F-04）：规整并纠正双扩展名（xxx_清稿.dwg.dxf → xxx_清稿.dxf/.dwg）。"""
        path = _normalize_double_extension(path)
        dxf = str(path).lower().endswith(".dxf")
        if os_path_exists(path):
            os_remove(path)
        fmt = saveas_format_for_release(self.release, dxf=dxf)
        try:
            # P-09：SaveAs 是 AutoCAD 重生成时最容易被拒的调用，忙等待重试
            _retry_com(lambda: doc.SaveAs(path, fmt))
        except Exception:
            try:
                _retry_com(lambda: doc.SaveAs(path))
            except Exception:
                pass
        # F-04：AutoCAD 偶发按保存格式自动追加扩展名（.dwg 路径 + DXF 格式 → .dwg.dxf），
        # 保存后扫描同目录，把双后缀产物重命名回正确路径。
        _repair_double_extension(path)
        return path

    def close_document(self, doc, save=False):
        try:
            doc.Close(bool(save))
        except Exception:
            pass
        if doc is self._doc:
            self._doc = None

    # ---------- 实体遍历 ----------

    def iter_entities(self, space):
        """安全遍历实体集合（允许在收集完成后统一删除）。

        P-09：Count/Item 在 AutoCAD 重生成/模态时可能被拒（RPC_E_CALL_REJECTED），
        统一忙等待重试，避免遍历中途整单崩溃。
        """
        i = 0
        while True:
            count = _retry_com(lambda: space.Count)
            if i >= count:
                break
            yield _retry_com(lambda: space.Item(i))
            i += 1

    # ---------- 布局空间（v0.1.156：图纸在 Layout 出图的情况） ----------

    def iter_layouts(self, doc):
        """遍历文档全部布局（含 Model）。COM 布局集合 Layouts。"""
        try:
            for i in range(doc.Layouts.Count):
                yield doc.Layouts.Item(i)
        except Exception:
            return

    def layout_space(self, layout):
        """布局的 Block 对象（图纸空间实体集合），失败返回 None。"""
        try:
            return layout.Block
        except Exception:
            return None

    def is_paperspace_layout(self, layout, model_name="Model"):
        """是否为图纸空间布局（排除 Model）。"""
        try:
            return str(layout.Name or "") != model_name
        except Exception:
            return False

    # ---------- 图层锁定（v0.1.156：锁定图层文字删不掉） ----------

    def get_layer_lock(self, doc, layer_name):
        try:
            return bool(doc.Layers.Item(layer_name).Lock)
        except Exception:
            return False

    def set_layer_lock(self, doc, layer_name, lock):
        try:
            doc.Layers.Item(layer_name).Lock = bool(lock)
        except Exception:
            pass

    # ---------- 对象类型识别（v0.1.156） ----------

    def is_table(self, ent):
        """表格对象（AcDbTable，标题栏用表格画的情况）。"""
        try:
            return ent.ObjectName == "AcDbTable"
        except Exception:
            return False

    def is_raster(self, ent):
        """光栅图像（扫描签名/电子图章/照片）。"""
        try:
            return ent.ObjectName == "AcDbRasterImage"
        except Exception:
            return False

    def is_xref(self, ent, doc):
        """块引用是否为外部参照（Xref 承载图框/标题栏）。"""
        try:
            if ent.ObjectName != "AcDbBlockReference":
                return False
            name = str(ent.Name or "")
            blk = doc.Blocks.Item(name)
            return bool(blk.IsXRef) if blk is not None else False
        except Exception:
            return False

    def table_cell_texts(self, ent, max_rows=200, max_cols=50):
        """读取表格对象全部单元格文字（AcDbTable.CellText）。"""
        try:
            n_r = int(ent.Rows)
            n_c = int(ent.Columns)
        except Exception:
            return []
        texts = []
        try:
            for i in range(min(n_r, max_rows)):
                for j in range(min(n_c, max_cols)):
                    try:
                        t = str(ent.GetCellText(i, j) or "").strip()
                    except Exception:
                        continue
                    if t:
                        texts.append(t)
        except Exception:
            pass
        return texts

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
        """从闭合多段线中提取矩形边界；非矩形返回 None。

        v0.1.156 全情况整改：
        - 圆角容差：顶点落在角部容差带内即可（圆角图框半径 ≤15mm 常见）
        - 斜置图框：计算主轴旋转角，把 4 顶点转正后取轴对齐矩形，
          返回 (minx, miny, maxx, maxy, rotation)——rotation 供文字坐标逆变换
          与打印走范围路线使用。异形（转正后仍不对齐）返回 None。
        """
        import math
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
        size = max(maxx - minx, maxy - miny)
        # 圆角容差：边长 2.5% + 12mm（覆盖常见圆角半径）
        tol = size * 0.025 + 12.0
        ok = True
        for (x, y) in pts:
            near_x = abs(x - minx) <= tol or abs(x - maxx) <= tol
            near_y = abs(y - miny) <= tol or abs(y - maxy) <= tol
            if not (near_x and near_y):
                ok = False
                break
        if ok:
            return (minx, miny, maxx, maxy, 0.0)

        # 斜置图框：求主轴旋转角（与水平夹角最小的边方向），转正后重算
        # 取一条边的方向角，多条边投票取众数
        angles = []
        for i in range(4):
            j = (i + 1) % 4
            a = math.atan2(pts[j][1] - pts[i][1], pts[j][0] - pts[i][0])
            # 归一到 [-pi/2, pi/2]（横竖边等价）
            while a > math.pi / 2:
                a -= math.pi
            while a < -math.pi / 2:
                a += math.pi
            angles.append(a)
        # 聚类：若 4 边两两接近（|a| 或 |a±π/2|），则图框规则
        ang = min(angles, key=lambda a: abs(a))
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        rot_pts = []
        cos, sin = math.cos(ang), math.sin(ang)
        for (x, y) in pts:
            dx, dy = x - cx, y - cy
            rot_pts.append((cx + dx * cos - dy * sin, cy + dx * sin + dy * cos))
        rxs = [p[0] for p in rot_pts]
        rys = [p[1] for p in rot_pts]
        rminx, rmaxx = min(rxs), max(rxs)
        rminy, rmaxy = min(rys), max(rys)
        rsize = max(rmaxx - rminx, rmaxy - rminy)
        rtol = rsize * 0.02 + 12.0
        for (x, y) in rot_pts:
            near_x = abs(x - rminx) <= rtol or abs(x - rmaxx) <= rtol
            near_y = abs(y - rminy) <= rtol or abs(y - rmaxy) <= rtol
            if not (near_x and near_y):
                return None  # 异形（如任意四边形），不处理
        # 转正后的矩形 + 旋转角（逆变换时用 -ang）
        return (rminx, rminy, rmaxx, rmaxy, -ang)

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

    def collect_block_attributes(self, ent):
        """N-01：读取块引用（AcDbBlockReference）的**属性文字**。

        标题栏块里"公司名/证书号/人名"常是块属性（AcDbAttribute），iter_entities
        收集不到顶层文字、炸开又失败时残留。属性实体由 GetAttributes() 返回，
        位置为**世界坐标**、可单独 Delete（不影响块定义）。

        返回 [(text, (minx,miny,maxx,maxy), attr_ent), ...]；失败返回 []。
        """
        out = []
        try:
            attrs = ent.GetAttributes()
        except Exception:
            return out
        for a in (attrs or []):
            try:
                if str(a.ObjectName) != "AcDbAttribute":
                    continue
                t = str(a.TextString or "")
                if not t:
                    continue
                b = self.get_bounds(a)
                if not b:
                    continue
                out.append((t, b, a))
            except Exception:  # noqa: BLE001
                continue
        return out

    def collect_block_nested_texts(self, ent):
        """N-01：读取块引用内的**嵌套文字**（块定义中的 TEXT/MTEXT，非属性）。

        嵌套文字实体属于块定义，直接 Delete 会破坏块定义（影响所有引用该块的
        实例），因此只用于**判定与提示**（调用方记 notes，提示人工在 AutoCAD
        炸开块后重试）。位置按块变换（插入点 + 旋转 + 缩放）换算到世界坐标。

        v0.1.163：**支持嵌套块递归**（块定义内再嵌 INSERT，标题栏常为二级嵌套）；
        ObjectName 比较统一规范化。返回 [(text, (minx,miny,maxx,maxy), ent, kind), ...]
        kind ∈ {"text", "attdef"}；attdef=固定属性（ATTDEF，Constant 属性文字：
        GetAttributes 不返回，需就地置空而非删除）。
        块名/块定义不可读时抛异常（调用方记日志，便于真机定位收集路径失败点）。
        """
        import math

        def _objname(e):
            try:
                return str(e.ObjectName or "")
            except Exception:
                return ""

        try:
            name = str(ent.Name or "")
            if not name:
                raise ValueError("块引用无 Name")
            blk = self._doc.Blocks.Item(name)
        except Exception as e:  # noqa: BLE001
            raise ValueError("块定义不可读（Name=%r）：%s" % (getattr(ent, "Name", "?"), e))

        try:
            ip = tuple(ent.InsertionPoint)
        except Exception:
            return []
        rot = 0.0
        try:
            rot = float(ent.Rotation)
        except Exception:
            pass
        sx = sy = 1.0
        try:
            sx = float(ent.XScaleFactor)
        except Exception:
            pass
        try:
            sy = float(ent.YScaleFactor)
        except Exception:
            pass
        cos, sin = math.cos(rot), math.sin(rot)

        def _wpt(x, y):
            x2, y2 = x * sx, y * sy
            return (ip[0] + x2 * cos - y2 * sin, ip[1] + x2 * sin + y2 * cos)

        def _walk(blkdef, depth):
            out = []
            if depth > 4:   # 防循环块引用无限递归
                return out
            for sub in blkdef:
                try:
                    on = _objname(sub)
                    if on == "AcDbBlockReference":
                        # 嵌套块递归：子块文字按本块变换叠加子块变换
                        out.extend(_walk_nested(sub, depth + 1))
                        continue
                    if on == "AcDbAttributeDefinition":
                        # v0.1.165：固定属性（ATTDEF，Constant）——GetAttributes 不返回，
                        # 公司名/证书号/部分签署值常以固定属性存在标题栏块内。
                        t = str(sub.TextString or "")
                        if not t:
                            continue
                        try:
                            mn, mx = sub.GetBoundingBox()
                        except Exception:
                            continue
                        pts = [_wpt(mn[0], mn[1]), _wpt(mx[0], mn[1]),
                               _wpt(mx[0], mx[1]), _wpt(mn[0], mx[1])]
                        box = (min(p[0] for p in pts), min(p[1] for p in pts),
                               max(p[0] for p in pts), max(p[1] for p in pts))
                        out.append((t, box, sub, "attdef"))
                        continue
                    if on not in self.TEXT_NAMES:
                        continue
                    t = str(sub.TextString or "")
                    if not t:
                        continue
                    mn, mx = sub.GetBoundingBox()
                    pts = [_wpt(mn[0], mn[1]), _wpt(mx[0], mn[1]),
                           _wpt(mx[0], mx[1]), _wpt(mn[0], mx[1])]
                    box = (min(p[0] for p in pts), min(p[1] for p in pts),
                           max(p[0] for p in pts), max(p[1] for p in pts))
                    out.append((t, box, sub, "text"))
                except Exception:  # noqa: BLE001
                    continue
            return out

        def _walk_nested(sub, depth):
            out = []
            if depth > 4:
                return out
            try:
                sname = str(sub.Name or "")
                if not sname:
                    return out
                sblk = self._doc.Blocks.Item(sname)
            except Exception:
                return out
            try:
                sip = tuple(sub.InsertionPoint)
            except Exception:
                sip = (0, 0, 0)
            srot = 0.0
            try:
                srot = float(sub.Rotation)
            except Exception:
                pass
            ssx = ssy = 1.0
            try:
                ssx = float(sub.XScaleFactor)
            except Exception:
                pass
            try:
                ssy = float(sub.YScaleFactor)
            except Exception:
                pass
            scos, ssin = math.cos(srot), math.sin(srot)

            def _swpt(x, y):
                x2, y2 = x * ssx, y * ssy
                return (sip[0] + x2 * scos - y2 * ssin, sip[1] + x2 * ssin + y2 * scos)

            for sub2 in sblk:
                try:
                    on2 = _objname(sub2)
                    if on2 == "AcDbBlockReference":
                        out.extend(_walk_nested(sub2, depth + 1))
                        continue
                    if on2 == "AcDbAttributeDefinition":
                        t2 = str(sub2.TextString or "")
                        if not t2:
                            continue
                        try:
                            mn, mx = sub2.GetBoundingBox()
                        except Exception:
                            continue
                        p1, p2 = _swpt(mn[0], mn[1]), _swpt(mx[0], mx[1])
                        pts = [_wpt(p1[0], p1[1]), _wpt(p2[0], p1[1]),
                               _wpt(p2[0], p2[1]), _wpt(p1[0], p2[1])]
                        box = (min(p[0] for p in pts), min(p[1] for p in pts),
                               max(p[0] for p in pts), max(p[1] for p in pts))
                        out.append((t2, box, sub2, "attdef"))
                        continue
                    if on2 not in self.TEXT_NAMES:
                        continue
                    t2 = str(sub2.TextString or "")
                    if not t2:
                        continue
                    mn, mx = sub2.GetBoundingBox()
                    # 子块文字：先子块变换，再乘父块变换
                    p1, p2 = _swpt(mn[0], mn[1]), _swpt(mx[0], mx[1])
                    pts = [_wpt(p1[0], p1[1]), _wpt(p2[0], p1[1]),
                           _wpt(p2[0], p2[1]), _wpt(p1[0], p2[1])]
                    box = (min(p[0] for p in pts), min(p[1] for p in pts),
                           max(p[0] for p in pts), max(p[1] for p in pts))
                    out.append((t2, box, sub2, "text"))
                except Exception:  # noqa: BLE001
                    continue
            return out

        return _walk(blk, 0)

    def convert_to_autocad_type(self, ent):
        """把代理/自定义实体（天正 TArch 等）转换为 AutoCAD 基础实体（原地转换）。

        AutoCAD 2010+ COM 提供 Document.ConvertToAutoCADType()，天正标题栏
        文字/图框经此转换后变 AcDbText/AcDbLine 等可读基础实体，是解决
        "代理实体读不到 TextString" 的正解。转换失败返回 False（走炸开兜底）。
        """
        try:
            self._doc.ConvertToAutoCADType(ent)
            return True
        except Exception:
            return False

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
        import win32com.client
        plot_cfg = cfg.get("plot", {})
        device = plot_cfg.get("device", "DWG To PDF.pc3")
        style_sheet = plot_cfg.get("style_sheet", "monochrome.ctb")
        margin = plot_cfg.get("margin_mm", 10)
        self._plot_warnings = []  # R2：每次打印重新收集

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
            # 2026-10-26 修复（本机 AutoCAD 2020 R23.1 实测）：
            # v0.1.154+ 改用「临时 PlotConfiguration」（doc.PlotConfigurations.Add）
            # 承载打印参数，但本机 pc.CenterPlot = True 直接抛
            # com_error(输入无效, AutoCAD.Application)，整条打印链路中断。
            # 改回已实测通过的 doc.ActiveLayout 路线：布局对象上的 ConfigName /
            # SetWindowToPlot / PlotType / PlotToFile 全部可用；打印后恢复原设置。
            layout = doc.ActiveLayout
            saved = {}
            for attr in ("ConfigName", "PlotType", "PaperUnits", "CenterPlot",
                         "PlotRotation", "UseStandardScale", "CanonicalMediaName",
                         "StandardScale"):
                try:
                    saved[attr] = getattr(layout, attr)
                except Exception:  # noqa: BLE001
                    pass

            def _try_set(obj, attr, val):
                """容错赋值：单个属性不可设不应中断整条打印链路。

                R2：失败不再静默，记录到 self._plot_warnings，处理后透出 notes。
                """
                try:
                    setattr(obj, attr, val)
                    return True
                except Exception as _se:  # noqa: BLE001
                    self._plot_warnings.append("布局打印属性 %s 设置失败：%s" % (attr, _se))
                    return False

            try:
                _try_set(layout, "ConfigName", device)  # Bug2：打印设备用 ConfigName
                _try_set(layout, "PaperUnits", PAPER_UNITS_MM)
                _try_set(layout, "CenterPlot", True)
                _try_set(layout, "PlotRotation",
                         ROT_0 if frame.width >= frame.height else ROT_90)
                if style_sheet:
                    _try_set(layout, "StyleSheet", style_sheet)
                # 2026-10-26 修复：_set_paper_size 返回是否真的匹配到合适纸张；
                # 没匹配上时必须用"布满"，1:1 会把图框裁掉。
                paper_ok = self._set_paper_size(layout, frame, margin)
                # 双保险：窗口打印优先 → 失败回退范围打印
                last_err = None
                try:
                    # Bug4：先存窗口，再切 PlotType；Bug5：坐标用 VARIANT 双精度数组
                    # 2026-10-26 修复：VARIANT 在 win32com.client 下，
                    # pythoncom.VARIANT 在本机 pywin32 不存在（原写法静默 AttributeError
                    # → 窗口打印永远失败回退范围打印，多图框全部挤成一页）。
                    lo = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                 [frame.minx, frame.miny])
                    hi = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                 [frame.maxx, frame.maxy])
                    layout.SetWindowToPlot(lo, hi)
                    layout.PlotType = PLOT_TYPE_WINDOW  # Bug3：acWindow=4
                    if paper_ok:
                        _try_set(layout, "UseStandardScale", False)
                        try:
                            layout.SetCustomScale(1.0, 1.0)
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        # 纸张没匹配上 → 布满，保证每框仍独立一页
                        _try_set(layout, "UseStandardScale", True)
                        _try_set(layout, "StandardScale", 0)
                    if self._plot_to_file(doc, pdf_path):
                        return
                except Exception as e:  # noqa: BLE001
                    last_err = e
                # 回退：范围打印（acExtents=1）
                try:
                    layout.PlotType = PLOT_TYPE_EXTENTS
                    _try_set(layout, "UseStandardScale", True)
                    _try_set(layout, "StandardScale", 0)
                    if self._plot_to_file(doc, pdf_path):
                        return
                except Exception as e2:  # noqa: BLE001
                    raise CadError("PDF 打印失败（窗口/范围双路线均失败）：%s / %s"
                                   % (last_err, e2))
                raise CadError("PDF 打印未产出文件（PlotToFile 已调用但文件不存在）：%s"
                               % pdf_path)
            finally:
                # 恢复布局原设置，避免污染图纸
                for attr, val in saved.items():
                    try:
                        setattr(layout, attr, val)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            if old_bg is not None:
                try:
                    doc.SetVariable("BACKGROUNDPLOT", old_bg)
                except Exception:
                    pass

    def _plot_to_file(self, doc, pdf_path, timeout=60):
        """调用 PlotToFile 并轮询确认 PDF 真正落盘。

        2026-10-25 实测（Bug6 衍生）：BACKGROUNDPLOT 为后台模式时 PlotToFile
        立即返回成功但文件永不生成，必须靠文件存在性判定真实结果。
        """
        import os as _os
        import time as _time
        if _os.path.exists(pdf_path):
            try:
                _os.remove(pdf_path)
            except Exception:  # noqa: BLE001
                pass
        called = False
        for call in (lambda: doc.ActiveLayout.PlotToFile(pdf_path),
                     lambda: doc.Plot.PlotToFile(pdf_path)):
            try:
                call()
                called = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not called:
            return False
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if _os.path.exists(pdf_path) and _os.path.getsize(pdf_path) > 0:
                return True
            _time.sleep(1.0)
        return False


    def _set_paper_size(self, pc, frame, margin):
        """选择与图框尺寸匹配的纸张（含边距）。

        2026-10-25 整改：匹配不到合适纸张时**不再抛异常中断**窗口打印，
        降级为默认纸张 + UseStandardScale=True; StandardScale=0（布满），
        窗口范围仍保证每框一页。
        2026-10-26：返回 bool——True=匹配到合适纸张（可 1:1），
        False=降级布满（调用方据此决定缩放方式，1:1 会裁切）。
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
                return True
            except Exception:  # noqa: BLE001
                pass
        # 降级：默认纸张 + 布满（不抛异常）
        try:
            pc.UseStandardScale = True
            pc.StandardScale = 0
        except Exception:  # noqa: BLE001
            pass
        return False

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


# F-04：双扩展名（.dwg.dxf / .dxf.dwg）规整与产物校正
_CAD_EXTS = (".dwg", ".dxf")


def _normalize_double_extension(path):
    """规整路径：xxx_清稿.dwg.dxf → xxx_清稿.dxf（取最后一个真实扩展名）。

    只处理 .dwg/.dxf 相互叠加的情况，其余原样返回。
    """
    lower = str(path).lower()
    for e1 in _CAD_EXTS:
        for e2 in _CAD_EXTS:
            double = e1 + e2
            if lower.endswith(double):
                return path[:-len(double)] + e2
    return path


def _repair_double_extension(path):
    """SaveAs 后扫描同目录：若 AutoCAD 生成了 path+'.dxf'/'.dwg' 的双后缀文件，
    重命名回期望的 path。"""
    import os
    path = _normalize_double_extension(path)
    d = os.path.dirname(path) or "."
    base = os.path.basename(path)
    for extra in _CAD_EXTS:
        bad = os.path.join(d, base + extra)
        if os.path.exists(bad):
            try:
                if os.path.exists(path):
                    os.remove(path)
                os.rename(bad, path)
            except Exception:
                pass
    return path
