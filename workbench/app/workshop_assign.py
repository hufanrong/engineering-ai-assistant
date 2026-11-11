# 繁工AI 本地解析工作台 - 车间资料自动划分（v0.1.27）
# 优先级：manual(人工) > cad_title(CAD标题栏/图名,设计院) > filename(文件名) > content(正文关键词)
# 平票/无法确认 → 待人工，不报错；人工修正后重建图谱即生效。
from . import atomic_io as _atomic_io
import datetime
import json
import os
import re
import threading

from . import config

_LEGACY_FILE = None      # 全局旧文件路径（迁移用）
_MIGRATED = False
_LOCK = threading.RLock()


# v0.1.214：非 None 时所有落点都用这个目录（单测/离线重解析的隔离钩子）。
_ISOLATED_DIR = None

# v0.1.235：车间登记册读缓存。
# list_by_workshop / get_workshop / detect_workshop / _queue_candidate 都会问
# 「这个名字人工确认过吗」，300 个文件就是 300 次读盘。以 (路径, mtime, size)
# 为键：同一进程内不重复读盘，写盘立即失效，也不会读到旧值。
_REG_CACHE = {}
_REG_CACHE_LOCK = threading.RLock()
_REG_CACHE_MAX = 32


def _assign_file(data_dir=None) -> str:
    """v0.1.138：车间归属按项目隔离——写入当前项目数据目录，
    未选择项目时回退全局目录（兼容单项目/迁移期）。

    v0.1.214 修：原来只认「当前项目」，不认调用方给的目录。于是在临时目录里
    做重解析（单测 / 离线校验）时，解析缓存和 index 都落进临时目录，
    **车间归属却写进用户真实项目**。实测事故：真实项目 322fef90 的
    workshop_assign.json 里 22 条有 21 条指向 /tmp/fgpath_*，全是测试样本，
    界面上表现为「待人工确认」从 0 涨到 10 —— 用户看到一堆自己没上传过的文件。
    这和 upload_queue 那次是同一类：同一个动作，两个落点算出两个目录。
    """
    ddir = data_dir or _ISOLATED_DIR
    if ddir:
        os.makedirs(ddir, exist_ok=True)
        return os.path.join(ddir, "workshop_assign.json")
    try:
        from . import project_manager as _pm
        cur = _pm.get_current_project()
        if cur:
            pdir = _pm.get_project_data_dir(cur["id"])
            os.makedirs(pdir, exist_ok=True)
            return os.path.join(pdir, "workshop_assign.json")
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, "workshop_assign.json")


def _legacy_file() -> str:
    global _LEGACY_FILE
    if _LEGACY_FILE is None:
        _LEGACY_FILE = os.path.join(config.DATA_DIR, "workshop_assign.json")
    return _LEGACY_FILE


def _migrate_legacy():
    """一次性迁移：旧全局 workshop_assign.json 按 sha 匹配各项目 index，
    把记录迁入对应项目目录；匹配不到的留在全局备份。"""
    global _MIGRATED
    if _MIGRATED:
        return
    _MIGRATED = True
    legacy = _legacy_file()
    if not os.path.exists(legacy):
        return
    try:
        with open(legacy, encoding="utf-8") as f:
            legacy_map = json.load(f)
        if not isinstance(legacy_map, dict) or not legacy_map:
            return
        from . import project_manager as _pm
        moved = 0
        for proj in _pm.list_projects():
            pdir = _pm.get_project_data_dir(proj["id"])
            idx_path = os.path.join(pdir, "index.json")
            if not os.path.exists(idx_path):
                continue
            with open(idx_path, encoding="utf-8") as f:
                idx = json.load(f)
            target = {}
            tpath = os.path.join(pdir, "workshop_assign.json")
            if os.path.exists(tpath):
                with open(tpath, encoding="utf-8") as f:
                    target = json.load(f)
            for sha, rec in legacy_map.items():
                if sha in idx and sha not in target:
                    target[sha] = rec
                    moved += 1
            if target:
                _atomic_io.write_json(tpath, target, indent=1)
        # 迁移后全局文件改名备份（保留可追溯）
        if moved > 0 or True:
            os.rename(legacy, legacy + ".migrated_bak")
    except Exception:  # noqa: BLE001
        pass


def _load(data_dir=None) -> dict:
    # 隔离目录下不做旧文件迁移：迁移是「全局 → 各项目」的一次性动作，
    # 在临时目录里跑会把用户真实的全局历史文件改名备份掉。
    if not (data_dir or _ISOLATED_DIR):
        _migrate_legacy()
    f = _assign_file(data_dir)
    if os.path.exists(f):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(m: dict, data_dir=None):
    f = _assign_file(data_dir)
    _atomic_io.write_json(f, m, indent=1)


# v0.1.141：空间单元识别增强——不只识别「N号车间」，还覆盖命名车间（磨浮车间）
# 与工程常见功能单元（锂辉石库/原料库/焙烧炉/配电室/泵站/堆场/选矿厂等），
# 文件名支持分段解析（0101-锂辉石库-防雷接地.dwg → 锂辉石库），
# 一切以项目资料为准：唯一命中即归，多候选/无法确认留人工。
# v0.1.141：name 用非贪婪最短匹配（原料库入库→原料库而非原料库入库），
# 允许 1 字核心名（泵站/堆场/料场）但限白名单，防「在现场」类误报
_WORKSHOP_RE = re.compile(
    r"(?P<num>\d{1,2}|[一二三四五六七八九十]+)\s*号?\s*车间"
    r"|(?P<name>[\u4e00-\u9fa5]{1,8}?)(?:车间|厂房|库房|配电室|化验室|控制室|变电站|配电站|泵站|堆场|料场|库|室|间|仓|房|站|场|区|厂)"
)
_ONE_CHAR_OK = ("泵", "堆", "料", "站", "库", "场", "室", "厂", "区", "仓", "房", "矿", "渣", "储")
_CN = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
       "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
# v0.1.139：命名车间干扰前缀清洗（如「今日磨浮车间」→ 磨浮车间）
_BAD_PREFIX = ("今日", "本次", "当天", "现在", "现场", "项目", "整个", "全部",
               "有关", "相关", "各个", "以及", "本", "该", "在", "和", "与",
               "及", "对", "将", "已", "正在", "进行", "使用", "安装",
               # v0.1.227：图纸正文里最常见的「引用式」开头。
               # 实测真实资料把"详见厂房结构图"抽成了车间名「详见厂房」。
               "详见", "参见", "见", "依据", "根据", "按照", "按", "如图", "见图")
# v0.1.141：明显非空间单元的组合黑名单（name+单元词 整体命中则跳过）
_BAD_FULL = ("数据库", "资料库", "文件库", "图纸库", "软件库", "程序库", "素材库", "样本库",
             "工具库", "资源库", "文档库", "代码库", "知识库", "模板库", "产品库", "模型库",
             "对象库", "数据库", "素材库",
             "办公室", "会议室", "休息室", "更衣室", "值班室", "档案室", "阅览室", "会客室",
             "活动室", "教室", "储藏室", "杂物室", "盥洗室", "卫生间", "茶水间",
             "网站", "工作站", "火车站", "汽车站", "地铁站", "高铁站",
             "地区", "区域", "小区", "郊区", "城区", "学区", "园区", "街道",
             "工厂", "厂家", "厂商", "现场", "操场", "市场", "广场", "机场", "战场",
             "会场", "考场", "商场", "运动场")
# 文件名分段时跳过的常见图纸类型词（不含空间单元信息）
_SKIP_SEG = ("图纸", "施工图", "平面图", "立面图", "剖面图", "系统图", "原理图", "布置图",
             "详图", "目录", "说明", "清单", "台账", "记录", "方案", "交底", "日志",
             "报告", "通知", "计划", "设计", "安装", "竣工", "防雷", "接地", "配线",
             "动力", "照明", "给排水", "暖通", "消防", "网络", "弱电", "强电")
# v0.1.177：**目录段**专用拒绝词表。
# 用户的资料目录里绝大多数段是「资料类别 / 项目阶段 / 文件容器」，
# 比如 `安装资料\选厂\竣工资料\图纸\...`，这些段一旦被当成空间单元，
# 会把整批文件错误地归到一个叫「选厂」「安装资料」的假车间里。
# 与 _SKIP_SEG 分开维护：_SKIP_SEG 是**文件名**里的图纸类型词，
# 而目录段还会出现更宽的容器词（资料/文档/电子版/扫描件/备份…），
# 混在一起会把「化验室」这类真单元也误伤，故独立成表。
_DIR_SEG_SUFFIX = (
    "资料", "文件", "文档", "台账", "清单", "记录", "表格", "汇总", "目录",
    "图纸", "方案", "报告", "说明", "交底", "日志", "计划", "总结", "通知",
    "备份", "附件", "照片", "图片", "扫描件", "电子版", "模板", "样例",
)
_DIR_SEG_REJECT = (
    # 容器 / 类别
    "资料", "文档", "文件", "文件夹", "新建文件夹", "资料夹", "电子版", "扫描件",
    "图片", "照片", "影像", "附件", "存档", "归档", "备份", "原件", "复印件",
    "表格", "表单", "台账", "记录", "清单", "模板", "样例", "示例", "测试", "临时",
    "草稿", "旧版", "新版本", "其他", "其它", "杂项", "综合", "通用", "待整理",
    # 项目阶段 / 业务条线
    "项目", "工程", "施工", "安装", "竣工", "验收", "移交", "交接", "监理", "业主",
    "设计", "招标", "投标", "合同", "结算", "变更", "签证", "进度", "造价",
    "安全", "质量", "环保", "会议", "培训", "汇报", "总结", "计划", "通知", "函件",
    "选厂", "选矿厂", "全厂", "厂区", "矿区", "矿山", "车间资料", "设备", "材料",
    # 中英文系统目录
    "desktop", "documents", "downloads", "users", "temp", "tmp", "backup",
    "新建文件夹(2)", "未命名", "根目录", "目录", "汇总", "合计", "分项",
)


def _clean_name(name: str):
    """去掉命名单元前的干扰前缀，返回核心名（1 字名保留，白名单在 _norm/_from_text 判断）。"""
    if not name:
        return None
    for b in _BAD_PREFIX:
        if name.startswith(b):
            name = name[len(b):]
            break
    return name


def _norm(raw: str):
    """识别空间单元：编号车间归一化（2号车间）；命名单元保留原名（磨浮车间/锂辉石库/配电室/泵站）。"""
    m = _WORKSHOP_RE.search(raw or "")
    if not m:
        return None
    if m.group("num"):
        n = _CN.get(m.group("num"), m.group("num"))
        return f"{n}号车间"
    raw_name = m.group("name")
    name = _clean_name(raw_name)
    if not name or "车间" in name or "车" in name:
        return None
    if len(name) == 1 and name not in _ONE_CHAR_OK:
        return None
    # 后缀用「原始 name 长度」切片（清洗前后长度不同会错位）
    suffix = m.group(0)[len(raw_name):]
    full = f"{name}{suffix}"
    # v0.1.141：黑名单改子串判断（项目资料数据库说明 含「数据库」→ 拒绝）
    if any(b in full for b in _BAD_FULL):
        return None
    return full


def _norm_filename(file_name: str):
    """文件名识别：先整名试，再按 -_（）空格 分段试（0101-锂辉石库-防雷接地.dwg → 锂辉石库）。"""
    w = _norm(file_name or "")
    if w:
        return w
    if not file_name:
        return None
    for seg in re.split(r"[-_（）()\[\]\s、，,./]+", file_name):
        seg = seg.strip()
        if len(seg) < 2:
            continue
        if seg.isdigit():
            continue
        if re.match(r"^\d{6,8}$", seg):
            continue
        if seg in _SKIP_SEG:
            continue
        w = _norm(seg)
        if w:
            return w
    return None


_TEXT_BOUNDARY = set(" \t\r\n:：、，,/|；;-—()（）[]【】\"'“”‘’")


def _from_text(text: str, limit=5):
    """正文关键词提取空间单元（取前 N 个去重）。

    v0.1.227：加两道闸，否则抓到的全是句子碎片。

    实测（2026-11-10，马诺诺真实资料 60 个文件跑完）：
        /api/workshops 返回的车间名里有
            "件与件之间"、"相国四站"、"详见厂"、"主减速机油站"、"中矿堆"
        这些不是车间，是图纸正文里的半句话。原因：`_WORKSHOP_RE` 的后缀集
        包含 `间/站/厂/区/场` 这类极常见字，一旦在**整篇正文**（一张流程图
        2 万 6 千字）上扫，必然命中"……件与件之间……"这种句子中间。
        危害不只是多了几个脏名字：车间清单是「按车间组卷 / 车间下拉筛选」的
        数据源，用户看到「件与件之间」会直接认为系统不可信。

    两道闸：
      ① **行首**：单元词必须出现在该行去掉前导空白后的开头。
         句子中间的"……件与件之间……""相国四站的设备"一律不要。
         宁可漏掉几个真实单元（用户可以手工指定），也不要往车间清单里塞脏名字。
      ② **短行**：所在行不超过 40 字。图签、设备表、目录里单元名都是短行；
         正文长句里的偶发命中一律不要。
    文件名与目录名两条路**不受影响** —— 那两条本来就带着确定的边界。
    """
    out = []
    tn = text or ""
    for m in _WORKSHOP_RE.finditer(tn):
        s = m.start()
        # 闸①：行首（允许前面只有空白）
        ls = tn.rfind("\n", 0, s) + 1
        le = tn.find("\n", s)
        if le < 0:
            le = len(tn)
        line = tn[ls:le]
        # 命中必须正好落在该行第一个非空白字符处
        if s != ls + (len(line) - len(line.lstrip())):
            continue
        # 闸②：短行
        if (le - ls) > 40:
            continue
        if m.group("num"):
            n = _CN.get(m.group("num"), m.group("num"))
            w = f"{n}号车间"
        else:
            raw_name = m.group("name")
            name = _clean_name(raw_name)
            if not name or "车间" in name or "车" in name:
                continue
            if len(name) == 1 and name not in _ONE_CHAR_OK:
                continue
            suffix = m.group(0)[len(raw_name):]
            full = f"{name}{suffix}"
            if any(b in full for b in _BAD_FULL):
                continue
            w = full
        if w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def _norm_dir_segment(seg: str):
    """把**目录名**直接当作空间单元名（v0.1.177）。

    为什么需要这一条：用户按车间/工艺单元分文件夹时，目录名常常就是那个单元名，
    而且**不带**「车间/厂房/库/区」后缀 —— 「重介质」「重介质分选」「磨浮」都是这种情况。
    上面 `_norm` 的后缀正则对这类名字一律返回 None，等于把最强的归属信号扔掉了。
    （实测：237 个资料全在 `安装资料\\选厂\\重介质\\` 下，96% 因此归不到车间。）

    只在**目录**段生效，不用于文件名（文件名里有太多「安装」「竣工」这类非单元词）。
    明显不是空间单元的通用词由 _DIR_SEG_REJECT 挡掉。
    """
    if not seg:
        return None
    s = seg.strip()
    # 允许中文 / 字母 / 数字 / 常见括号连字符；其它（标点、空格串）一律不当单元名
    if not re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9（）()#\-_. ]{2,20}", s):
        return None
    # 去掉编号前缀：0101-重介质 / 01 重介质 / 3#重介质 → 重介质
    core = re.sub(r"^[0-9]{1,4}\s*[-_.#、]\s*", "", s).strip()
    core = re.sub(r"^[0-9]+#\s*", "", core).strip()
    core = _clean_name(core)
    if not core:
        return None
    core = core.strip()
    if not (2 <= len(core) <= 8):
        return None
    if core in _DIR_SEG_REJECT or core in _SKIP_SEG:
        return None
    # 容器后缀：真正的空间单元名不会以「资料/文件/台账」结尾
    # （竣工资料、安装文件、设备台账 这类都是目录用途，不是车间）
    if core.endswith(_DIR_SEG_SUFFIX):
        return None
    if any(b in core for b in _BAD_FULL):
        return None
    # 纯数字 / 纯字母的目录名不是单元名
    if re.fullmatch(r"[0-9A-Za-z_. \-]+", core):
        return None
    # 带版本/日期/批次痕迹的目录名跳过
    if re.search(r"([0-9]{6,8}|备份|旧版|新版本|临时|测试|样例|模板|副本)$", core):
        return None
    # 工艺单元可以不带「车间/库/区」后缀，但不能是「XX作业」「XX工作」这种动作词，
    # 也不能是单字（单字空间名如「库」必须靠 _norm 的后缀识别，不能在这里放行）
    if re.search(r"(作业|工作|管理|检查|规定|制度|办法|要求|标准|规范)$", core):
        return None
    return core


def _dir_unit(seg: str):
    """一个**目录段**代表的空间单元（v0.1.177）。

    两条通道：
    1) `_norm` 标准后缀识别 —— 能归一化编号（01号车间 → 1号车间），
       但必须再过一遍 _DIR_SEG_REJECT：`选矿厂` 会被 `_norm` 认成空间单元，
       其实它是整个厂的容器名，不能当车间。
    2) `_norm_dir_segment` —— 认「重介质」「磨浮」这类**无后缀**工艺单元。
    """
    w = _norm(seg)
    if w and w not in _DIR_SEG_REJECT and not w.endswith(_DIR_SEG_SUFFIX):
        return w
    return _norm_dir_segment(seg)


def _norm_path(path: str):
    """v0.1.143：目录路径信号——用户资料一般按车间分文件夹，
    目录名（磨浮车间/锂辉石库/0101-主厂房）是最强线索，优先于文件名。

    v0.1.177 两条修正（都是实测事故）：
    ① **只认目录段，绝不把文件名当目录段**。原实现从深到浅逐段调
       `_norm_filename`，最后一段是文件名也被切分识别 —— `0000-熟料送存仓除尘系统-重介质.pdf`
       于是返回「熟料送存仓」，把明明放在 `重介质` 目录下的文件归错门，这就是实测里
       「反而误识别熟料送存仓、锂辉石库」的来源。文件名信号由 detect_workshop 的
       独立通道（priority 0.75）负责，两条通道不能互相串。
    ② **无后缀工艺单元**（重介质/磨浮/浮选）原来一律返回 None，
       237 个放在 `安装资料/选厂/重介质/` 下的资料因此 96% 归不到车间。
    """
    if not path:
        return None
    segs = [s.strip() for s in re.split(r"[\\/]+", path or "")]
    segs = [s for s in segs
            if s and s not in (".", "..") and not re.match(r"^[A-Za-z]:$", s)]
    # 末尾若是文件名（带扩展名）就剔掉；只有路径整体是目录时才保留最后一段
    if segs and re.search(r"\.[A-Za-z0-9]{1,5}$", segs[-1]):
        segs = segs[:-1]
    # 由深到浅：离文件最近的目录名最能说明该文件的归属
    for seg in reversed(segs):
        w = _dir_unit(seg)
        if w:
            return w
    # 兜底：段名里包含项目已确认过的空间单元
    known = _known_set()
    for seg in reversed(segs):
        for k in sorted(known, key=len, reverse=True):
            if k and k in seg:
                return k
    return None


# v0.1.236：**设备台账就是权威车间清单**。
# 用户 2026-11-11 追加指令原话：
#   「在设备清单中已经给出多个车间了,里面已经包含实际的车间名称了,
#     不要在生成其他乱七八糟的车间名字」
# 设备台账（index.json 的 devices）里每一行都带人填的 workshop 列，那就是这个
# 项目真实存在的全部车间。既然权威清单已经有了，再让算法从文件名/正文里猜名字，
# 猜出来的必然是错的（「建宇建主减速机油站」就是这么来的）。
# 所以：台账非空时，**只有台账里的名字算车间**；猜出来的名字不在台账里 → 直接作废，
# 连待审批队列都不进（用户不需要审一个显然不存在的车间）。
_LEDGER_CACHE = {}
_LEDGER_CACHE_LOCK = threading.RLock()


def ledger_workshop_names(data_dir=None) -> set:
    """本项目设备台账行里的车间名集合（权威）。台账为空 → 返回空集（退回旧逻辑）。"""
    d = _dir_for(data_dir)
    if not d:
        return set()
    f = os.path.join(d, "index.json")
    if not os.path.isfile(f):
        return set()
    try:
        st = os.stat(f)
    except OSError:
        return set()
    key = (f, st.st_mtime_ns, st.st_size)
    with _LEDGER_CACHE_LOCK:
        hit = _LEDGER_CACHE.get(key)
    if hit is not None:
        return hit
    names = set()
    try:
        with open(f, encoding="utf-8") as fh:
            idx = json.load(fh) or {}
        for dev in (idx.get("devices") or {}).values():
            if not isinstance(dev, dict):
                continue
            w = str(dev.get("workshop") or "").strip()
            if w:
                names.add(w)
    except Exception:  # noqa: BLE001
        names = set()
    with _LEDGER_CACHE_LOCK:
        if len(_LEDGER_CACHE) >= 16:
            _LEDGER_CACHE.clear()
        _LEDGER_CACHE[key] = names
    return names


def _ledger_is_authoritative(data_dir=None) -> bool:
    """台账里有车间名 → 台账就是唯一权威清单（v0.1.237）。

    单独抽出来是因为判断点有三处（检测出口 / 候选清单 / 待审批分组），
    三处口径必须同一份实现，否则又成「同一件事两个答案」。
    """
    return bool(ledger_workshop_names(data_dir))


def is_workshop_allowed(name: str, data_dir=None) -> bool:
    """这个名字能不能作为正式车间用（v0.1.236）。

    口径：① 人工确认过的（registry）→ 可以；
         ② 设备台账里出现的 → 可以（用户自己填的结构化列，权威）；
         ③ 其余 → 不可以（自动推导出来的猜测，绝不当车间）。
    台账非空时，② 同时起到「白名单」作用：猜出来的名字不在台账里一律作废。
    """
    n = (name or "").strip()
    if not n or n == "未归车间":
        return False
    if is_workshop_confirmed(n, data_dir):
        return True
    return n in ledger_workshop_names(data_dir)


def _match_ledger(hay: str, data_dir=None) -> list:
    """在台账车间名里找 hay（文件名/路径）命中的那些，按名字长度降序。

    用台账名反查而不是正查：台账是权威清单，它命中就说明这份文件属于该车间，
    比正则猜「xxx车间」可靠；长的名字优先（「尾矿输送」先于「尾矿库」）。
    """
    names = ledger_workshop_names(data_dir)
    if not names or not hay:
        return []
    hit = [n for n in names if n in hay]
    if not hit:
        return []
    hit.sort(key=len, reverse=True)
    # 互相包含的名字（尾矿库 / 尾矿输送）只留命中更长的那个
    out = []
    for n in hit:
        if any(n in kept for kept in out):
            continue
        out.append(n)
    return out


def _known_set() -> set:
    """项目已**人工确认**的车间集合（v0.1.235 改口径）。

    旧实现（v0.1.143）从 `workshop_assign.json` 的**所有记录**里学车间，只要有人
    自动推导出一个名字，下一轮它就变成"已知车间"去兜底命中别的文件。
    实测后果：`主减速机油站`「件与件之间」这类句子碎片一次落盘就永久自我强化，
    越跑越多，用户看到车间清单里出现根本不是车间的名字。

    现在只认登记册（人工确认过的）：自动推导的名字**没有资格**给别的文件做兜底。
    这正是用户 2026-11-11 说的「人工确认该车间存在时，再正式建立该车间」。
    """
    names = {r["name"] for r in list_registry() if r.get("name")}
    # v0.1.236：台账车间同属权威（用户明确「设备清单里已经给出车间了」）
    names |= ledger_workshop_names()
    return names


def detect_workshop(file_name: str = "", text: str = "", structure: dict = None,
                    file_path: str = "") -> dict:
    """按优先级识别车间 → {workshop, source, confidence, candidates}。
    无法唯一确认 → workshop=None，candidates 列出候选（供人工）。
    v0.1.143：新增目录路径信号（file_path，0.85）与已知车间兜底（0.6）。
    v0.1.235：结果统一过一遍人工否决名单（_veto_result）——被否决的名字
    不许再出现在 workshop 或 candidates 里。"""
    return _veto_result(_detect_workshop_raw(file_name, text, structure, file_path))


def _detect_workshop_raw(file_name: str = "", text: str = "", structure: dict = None,
                         file_path: str = "") -> dict:
    structure = structure or {}
    # 0) **设备台账优先**（v0.1.236）：台账里已经有人填好的车间名，先拿它反查
    hay = f"{file_path or ''} {file_name or ''}"
    led = _match_ledger(hay)
    if len(led) == 1:
        return {"workshop": led[0], "source": "ledger", "confidence": 0.95,
                "candidates": [led[0]]}
    if len(led) > 1:
        # 文件名同时命中多个台账车间（如「尾矿库-尾矿输送-图.dwg」）→ 不强行归一个
        return {"workshop": None, "source": "ledger_multi", "confidence": 0.35,
                "candidates": led}
    # 1) CAD 标题栏图名（设计院）
    cad_title = ""
    sp = structure.get("spatial") or {}
    tb = sp.get("title_block") or {}
    if tb.get("图名"):
        cad_title = tb["图名"]
    if cad_title:
        w = _norm(cad_title)
        if w:
            return {"workshop": w, "source": "cad_title", "confidence": 0.9, "candidates": [w]}
    # 2) 目录路径（用户按车间分文件夹是最强工程信号；v0.1.143 新增）
    if file_path:
        w = _norm_path(file_path)
        if w:
            return {"workshop": w, "source": "file_path", "confidence": 0.85, "candidates": [w]}
    # 3) 文件名（v0.1.141：分段解析，识别 0101-锂辉石库-xxx.dwg → 锂辉石库）
    if file_name:
        w = _norm_filename(file_name)
        if w:
            return {"workshop": w, "source": "filename", "confidence": 0.75, "candidates": [w]}
    # 4) 正文关键词
    cands = _from_text(text or "", limit=3)
    if len(cands) == 1:
        return {"workshop": cands[0], "source": "content", "confidence": 0.55, "candidates": cands}
    if len(cands) > 1:
        # 多车间（如台账/清单跨车间）→ 不强行归单车间，列候选
        return {"workshop": None, "source": "content_multi", "confidence": 0.3, "candidates": cands}
    # 5) 已知车间兜底（v0.1.143）：项目已确认车间，文件名/路径包含该车间名 → 命中
    known = _known_set()
    if known:
        hay = f"{file_path or ''} {file_name or ''}"
        for w in sorted(known, key=len, reverse=True):
            if w and w in hay:
                return {"workshop": w, "source": "known", "confidence": 0.6, "candidates": [w]}
    return {"workshop": None, "source": "none", "confidence": 0.0, "candidates": []}


def _veto(name):
    """v0.1.235：人工否决过的名字直接作废。

    detect_workshop 的四条自动通道（标题栏/路径/文件名/正文）都会产出名字，
    只要这个名字被人否决过一次，后面再命中就不该再冒出来 —— 否则用户否决
    「主减速机油站」，下一次扫描它又回到待审批队列，等于否决没生效。
    """
    if not name:
        return name
    return None if is_workshop_rejected(name) else name


def _veto_result(info: dict) -> dict:
    """把 detect_workshop 的结果过两道闸（v0.1.235 / v0.1.236）。

    闸① 人工否决名单：否决过的名字不许再出现在 workshop 或 candidates 里。
    闸② **台账白名单**（v0.1.236，用户 2026-11-11「在设备清单中已经给出多个车间了…
        不要在生成其他乱七八糟的车间名字」）：台账里已经有真实车间名时，任何
        不在台账里的名字都不是车间 —— 直接从 workshop 和 candidates 双双剔除，
        连待审批队列都不进（不必让人去审一个明显不存在的东西）。

    为什么闸② 还得在这里做，而不是只去掉正则：detect 现在有四条通道（标题栏/
    标题/路径/文件名/正文），挨个通道加白名单必然漏一路 —— 收口到出口处统一判定，
    以后再加通道也跑不掉。
    """
    if not isinstance(info, dict):
        return info
    info["candidates"] = [c for c in (info.get("candidates") or []) if not is_workshop_rejected(c)]
    if info.get("workshop") and is_workshop_rejected(info["workshop"]):
        info["workshop"] = None
        info["source"] = "rejected"
        if not info["candidates"]:
            info["confidence"] = 0.0
    # 闸②：台账白名单
    led = ledger_workshop_names()
    if led:
        if info.get("candidates"):
            kept = [c for c in info["candidates"] if c in led or is_workshop_confirmed(c)]
            info["candidates"] = kept
        if info.get("workshop") and not (
                info["workshop"] in led or is_workshop_confirmed(info["workshop"])):
            info["workshop"] = None
            if not info["source"].endswith("_multi"):
                info["source"] = "not_in_ledger"
            info["confidence"] = 0.0
    return info


def assign_workshop(sha: str, file_name: str = "", text: str = "", structure: dict = None,
                    force: bool = False, file_path: str = "", data_dir: str = "") -> dict:
    """解析后自动归车间；已有人工登记不覆盖（force=True 才覆盖）。
    v0.1.143：新增 file_path 目录路径信号（网页上传传 orig_path，扫描传绝对路径）。

    v0.1.214：新增 data_dir —— 临时目录场景（单测 / 离线重解析）必须能指定落点。
    不传时行为不变（写当前项目）。
    """
    if data_dir:
        global _ISOLATED_DIR
        with _LOCK:
            _prev = _ISOLATED_DIR
            try:
                _ISOLATED_DIR = data_dir
                return _assign_workshop_impl(sha, file_name, text, structure, force, file_path)
            finally:
                _ISOLATED_DIR = _prev
    return _assign_workshop_impl(sha, file_name, text, structure, force, file_path)


def _assign_workshop_impl(sha, file_name, text, structure, force, file_path):
    m = _load()
    existing = m.get(sha)
    if existing and existing.get("source") == "manual" and not force:
        return existing
    info = detect_workshop(file_name, text, structure, file_path)

    # v0.1.235（用户 2026-11-11 指令）：
    #   「所有新建立的车间必须交由人工审批，人工确认该车间存在时，再正式建立该车间，
    #     否则就不要建立车间」
    # 自动推导出来的名字**不得**直接成为车间。它降级为「候选归属」：
    # 文件仍然临时归入这个名字下面（用户要求"可以先将文件暂时归类进去"），
    # 但该车间在正式清单里是**待审批**状态，confirmed=False。
    # 只有 manual_assign / approve_workshop 走过后，confirmed 才为 True。
    _ws = info["workshop"]
    _confirmed = bool(_ws) and is_workshop_confirmed(_ws)
    rec = {
        "sha256": sha,
        "file_name": file_name,
        "workshop": _ws,
        "source": info["source"],
        "confidence": info["confidence"],
        "candidates": info["candidates"],
        "file_path": file_path,
        "confirmed": _confirmed,
        "ts": datetime.datetime.now().isoformat(),
    }
    m[sha] = rec
    _save(m)
    # 自动推导出的新名字进审批队列（人工确认前只算候选车间）
    if _ws:
        _queue_candidate(_ws, file_name=file_name, sha=sha, source=info["source"])
    return rec


def _registry_file(data_dir=None) -> str:
    """车间登记册：**只有人工确认过的车间**才写在这里（v0.1.235）。

    为什么单独一个文件，而不是从 workshop_assign.json 里推导：
    以前 `_known_set()` 是「从所有记录里学车间」，于是自动推导出来的
    「主减速机油站」「件与件之间」「相国四站」一旦落盘，第二轮就变成"已知车间"，
    反过来给别的文件做兜底命中 —— **脏名字自我强化**，越跑越脏。
    登记册只由人工动作写入，自动推导连读它的资格都没有（只读，不写）。
    """
    d = _dir_for(data_dir)
    return os.path.join(d, "workshop_registry.json") if d else None


def _candidates_file(data_dir=None) -> str:
    """待审批车间队列（v0.1.235）：自动推导出、还没人工确认的名字。"""
    d = _dir_for(data_dir)
    return os.path.join(d, "workshop_candidates.json") if d else None


def _dir_for(data_dir=None):
    """统一落点解析：显式 data_dir > 隔离目录 > 当前项目 > 全局。

    v0.1.238：顺序反过来了（原来是「隔离目录 > 显式 data_dir」）。这不是口味问题：
    `_assign_file` 一直是 `data_dir or _ISOLATED_DIR`（显式优先），而 `_dir_for`
    却是隔离优先 —— 同一个模块里「该用哪个目录」有两个答案。实测后果：调用方
    `build_relations(data_dir=d1)` 传了目录，闸门却去 d1 之外的隔离根读 index.json，
    读不到 → `ledger_workshop_names()` 返回空集 → 台账白名单静默失效，
    设备级「1号车间 / 3号车间」照样漏出去（而 probe 直接用隔离根当台账目录时是好的，
    因为那时两个答案恰好重合）。两个函数现在同一顺序。
    """
    if data_dir:
        return data_dir
    if _ISOLATED_DIR:
        return _ISOLATED_DIR
    af = _assign_file()
    return os.path.dirname(af) if af else None


def _load_registry(data_dir=None) -> dict:
    f = _registry_file(data_dir)
    if not f or not os.path.exists(f):
        return {}
    try:
        st = os.stat(f)
    except OSError:
        return {}
    key = (f, st.st_mtime_ns, st.st_size)
    with _REG_CACHE_LOCK:
        hit = _REG_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(f, encoding="utf-8") as fh:
            reg = json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(reg, dict):
        return {}
    with _REG_CACHE_LOCK:
        if len(_REG_CACHE) >= _REG_CACHE_MAX:
            _REG_CACHE.clear()
        _REG_CACHE[key] = reg
    return reg


def _save_registry(reg: dict, data_dir=None) -> bool:
    f = _registry_file(data_dir)
    if not f:
        return False
    try:
        _atomic_io.write_json(f, reg)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        # 写盘后立刻失效，避免同进程读到写之前的缓存
        with _REG_CACHE_LOCK:
            _REG_CACHE.clear()


def _load_candidates(data_dir=None) -> dict:
    f = _candidates_file(data_dir)
    if not f or not os.path.exists(f):
        return {}
    try:
        return json.loads(open(f, encoding="utf-8").read()) or {}
    except Exception:  # noqa: BLE001
        return {}


def _save_candidates(c: dict, data_dir=None) -> bool:
    f = _candidates_file(data_dir)
    if not f:
        return False
    try:
        _atomic_io.write_json(f, c)
        return True
    except Exception:  # noqa: BLE001
        return False


def _queue_candidate(name: str, file_name: str = "", sha: str = "", source: str = "") -> None:
    """把自动推导出的车间名登记进待审批队列（v0.1.235）。

    只记「证据」不记「决定」：同一名字多次命中累加样本，供人工判断这是不是真车间。
    人工确认过的名字不进队列。
    """
    name = (name or "").strip()
    if not name or name == "未归车间":
        return
    if is_workshop_confirmed(name):
        return
    c = _load_candidates()
    rec = c.get(name) or {"name": name, "count": 0, "samples": [], "sources": [],
                          "first_ts": datetime.datetime.now().isoformat()}
    rec["count"] = int(rec.get("count", 0)) + 1
    if file_name and file_name not in rec.get("samples", []):
        rec.setdefault("samples", []).append(file_name)
        rec["samples"] = rec["samples"][-8:]
    if source and source not in rec.get("sources", []):
        rec.setdefault("sources", []).append(source)
    rec["last_ts"] = datetime.datetime.now().isoformat()
    c[name] = rec
    _save_candidates(c)


def is_workshop_confirmed(name: str, data_dir=None) -> bool:
    """该车间名是否已被人工确认（v0.1.235）。

    判定口径严格：**只认登记册**。旧的 workshop_assign.json 里历史遗留的
    自动推导记录一律不算确认 —— 否则升级后脏名字依旧是"正式车间"，
    等于这次改造没生效。
    """
    name = (name or "").strip()
    if not name:
        return False
    reg = _load_registry(data_dir)
    rec = reg.get(name)
    if isinstance(rec, dict):
        return bool(rec.get("confirmed"))
    return False


def approve_workshop(name: str, approved_by: str = "", note: str = "") -> dict:
    """人工确认车间存在 → 正式建立（v0.1.235）。

    确认后：① 写登记册；② 从待审批队列移除；③ 把此前**临时归入**该名字的文件
    全部转正（confirmed=True），这样"先归类、后确认"两条要求同时满足。
    """
    name = (name or "").strip()
    if not name or name == "未归车间":
        raise ValueError("车间名不能为空")
    reg = _load_registry()
    reg[name] = {
        "name": name,
        "confirmed": True,
        "confirmed_by": approved_by or "user",
        "confirmed_ts": datetime.datetime.now().isoformat(),
        "note": note or "",
    }
    ok_reg = _save_registry(reg)
    c = _load_candidates()
    c.pop(name, None)
    _save_candidates(c)
    # 临时归入该名字的文件转正
    m = _load()
    n = 0
    for sha, rec in m.items():
        if (rec.get("workshop") or "").strip() == name and not rec.get("confirmed"):
            rec["confirmed"] = True
            n += 1
    if n:
        _save(m)
    return {"workshop": name, "registry_saved": ok_reg, "files_promoted": n}


def reject_workshop(name: str, rejected_by: str = "", note: str = "") -> dict:
    """人工否决该车间不存在 → 不建立（v0.1.235）。

    否决后：① 名字从队列移除并记入黑名单，下次自动推导命中它直接当无效；
    ② 原先临时归入它的文件**退回未归车间**（不留假归属）。
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("车间名不能为空")
    reg = _load_registry()
    reg[name] = {
        "name": name,
        "confirmed": False,
        "rejected": True,
        "rejected_by": rejected_by or "user",
        "rejected_ts": datetime.datetime.now().isoformat(),
        "note": note or "",
    }
    _save_registry(reg)
    c = _load_candidates()
    c.pop(name, None)
    _save_candidates(c)
    m = _load()
    n = 0
    for sha, rec in m.items():
        if (rec.get("workshop") or "").strip() == name:
            rec["workshop"] = None
            rec["confirmed"] = False
            rec["candidates"] = []
            rec["source"] = "rejected"
            n += 1
    if n:
        _save(m)
    return {"workshop": name, "files_released": n}


def is_workshop_rejected(name: str) -> bool:
    """人工已否决的名字（v0.1.235）：自动推导再次命中它应当直接无效。"""
    rec = _load_registry().get((name or "").strip())
    return bool(isinstance(rec, dict) and rec.get("rejected"))


def list_candidates() -> list:
    """待审批车间清单（v0.1.235）：按命中样本数降序，给界面用。

    v0.1.237（实测复现）：正式清单已按台账裁干净了，**待审批区还在挂「选矿厂」**
    —— 这个名字是文件名猜出来的，台账里 19 个车间没有它。用户看到的仍然是
    一个「乱七八糟的车间名」，他的指令自然没被满足。所以候选队列与待审批分组
    必须跟正式清单用同一把尺子（`is_workshop_allowed`），否则只是把脏名字
    从左边挪到了右边。
    """
    c = _load_candidates()
    rows = []
    for name, rec in c.items():
        if is_workshop_confirmed(name) or is_workshop_rejected(name):
            continue
        # 台账权威时，台账外的名字连「待审批」都不显示（人要审的是真的没定的事，
        # 不是审「这个猜出来的名字像不像车间」）
        if _ledger_is_authoritative() and name not in ledger_workshop_names():
            continue
        rows.append({"name": name,
                     "count": int(rec.get("count", 0)),
                     "samples": rec.get("samples", []),
                     "sources": rec.get("sources", []),
                     "first_ts": rec.get("first_ts", ""),
                     "last_ts": rec.get("last_ts", "")})
    rows.sort(key=lambda x: (-x["count"], x["name"]))
    return rows


def list_registry() -> list:
    """已人工确认的车间（v0.1.235）。"""
    reg = _load_registry()
    return [{"name": k, **v} for k, v in sorted(reg.items()) if isinstance(v, dict)
            and v.get("confirmed")]


def manual_assign(sha: str, workshop: str, file_name: str = "") -> dict:
    m = _load()
    rec = m.get(sha, {})
    # v0.1.235：人工指定 = 人工确认该车间存在。必须同时写登记册，
    # 否则会出现「文件已人工指定、但车间在清单里仍是待审批」的自相矛盾。
    if workshop and workshop != "未归车间":
        approve_workshop(workshop, approved_by="manual_assign", note="人工指定文件车间")
    rec.update({
        "sha256": sha, "file_name": file_name or rec.get("file_name", ""),
        "workshop": workshop, "source": "manual", "confidence": 1.0,
        "candidates": [workshop], "confirmed": bool(workshop), "ts": datetime.datetime.now().isoformat(),
    })
    m[sha] = rec
    _save(m)
    return rec


def batch_assign(shas: list, workshop: str) -> int:
    m = _load()
    # v0.1.235：批量人工指定同样是人工确认该车间存在
    if workshop and workshop != "未归车间":
        approve_workshop(workshop, approved_by="batch_assign", note="批量指定文件车间")
    n = 0
    for sha in shas:
        rec = m.get(sha, {})
        rec.update({"sha256": sha, "workshop": workshop, "source": "manual",
                    "confidence": 1.0, "candidates": [workshop],
                    "confirmed": bool(workshop), "ts": datetime.datetime.now().isoformat()})
        m[sha] = rec
        n += 1
    _save(m)
    return n


def re_auto_unassigned() -> int:
    """重新自动识别：未归车间 + 低置信度（<0.6）的文件，人工登记跳过。
    v0.1.143：修复空转——此前调用 scanner._load_cache 但该函数不存在，
    hasattr 恒 False → 所有文件 continue，按钮永远返回 0。
    现在正确读取解析缓存，并用 index 里的路径（orig_path/绝对路径）作目录信号。"""
    from . import scanner
    idx = scanner._load_index()
    n = 0
    for sha, info in idx.items():
        if sha in scanner.INDEX_RESERVED_KEYS or not isinstance(info, dict):
            continue
        rec = _load().get(sha, {})
        if rec.get("source") == "manual":
            continue
        if rec.get("workshop") and float(rec.get("confidence", 0)) >= 0.6:
            continue
        cache = scanner._load_cache(sha)
        fname = (cache or {}).get("file_name") or info.get("file_name", "")
        text = (cache or {}).get("text", "") or ""
        structure = (cache or {}).get("structure") or {}
        fpath = info.get("orig_path") or info.get("file_path", "") or ""
        new_rec = assign_workshop(sha, fname, text, structure, force=True, file_path=fpath)
        if new_rec.get("workshop"):
            n += 1
    return n


def list_pending_by_workshop() -> dict:
    """{候选车间名: [临时归入它的文件]}（v0.1.235）。

    用户要求「可以先将文件暂时归类进去」——所以文件不丢，但**分组归属在
    审批通过前不算正式车间**。界面用这份数据渲染「待审批车间」区，
    每条带确认/否决按钮。
    """
    m = _load()
    out = {}
    led = ledger_workshop_names()
    for sha, rec in m.items():
        w = (rec.get("workshop") or "").strip()
        if not w or is_workshop_confirmed(w):
            continue
        if is_workshop_rejected(w):
            continue
        # v0.1.237：台账外名字不显示为「待审批车间」（口径同 list_candidates）
        if led and w not in led:
            continue
        out.setdefault(w, []).append(rec)
    for w in out:
        out[w].sort(key=lambda r: r.get("ts", ""), reverse=True)
    return out


def approve_all_candidates(approved_by: str = "batch_approve", note: str = "") -> dict:
    """把当前待审批队列**全部**确认为正式车间（v0.1.235）。

    仍然是人触发的动作（界面上一个按钮），不是自动确认——用途是升级后
    把历史项目已经对过的车间批量转正，免得一个个点。
    """
    names = [c["name"] for c in list_candidates()]
    ok, promoted = 0, 0
    for name in names:
        try:
            r = approve_workshop(name, approved_by=approved_by, note=note or "批量确认")
            ok += 1 if r.get("registry_saved") else 0
            promoted += int(r.get("files_promoted") or 0)
        except Exception:  # noqa: BLE001
            continue
    return {"approved": ok, "files_promoted": promoted, "names": names}


def list_by_workshop(include_candidates: bool = False) -> dict:
    """{workshop: [rec], "未归车间": [rec]} —— **只含已人工确认的车间**（v0.1.235）。

    自动推导出、还没审批的名字**不出现在这里**（否则它就成了正式车间，
    用户要的「否则就不要建立车间」落空）。那些文件仍可见：
    `list_pending_by_workshop()` 把它们按候选名字分组返回，界面单独一区。

    include_candidates=True 保留旧行为（把它们也当 key 返回），仅供需要
    「看文件暂时归在哪」的导出/排查场景，不用于对外车间清单。
    """
    m = _load()
    out = {}
    for sha, rec in m.items():
        w = (rec.get("workshop") or "").strip()
        if not w:
            out.setdefault("未归车间", []).append(rec)
            continue
        if include_candidates or is_workshop_confirmed(w):
            out.setdefault(w, []).append(rec)
    for w in out:
        out[w].sort(key=lambda r: r.get("ts", ""), reverse=True)
    return out


def get_workshop(sha: str) -> str:
    """relations 用：取登记车间（人工优先），无则 None。

    v0.1.235：只返回**已确认**车间。候选名字（自动推导、未审批）返回 None ——
    否则关系图谱/按车间组卷会把「主减速机油站」当成真车间写进去，
    用户否决了也没用（下游已经把假车间固化了）。
    """
    m = _load()
    rec = m.get(sha)
    w = (rec or {}).get("workshop")
    if not w:
        return None
    return w if is_workshop_confirmed(w) else None
