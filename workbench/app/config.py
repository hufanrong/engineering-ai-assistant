# 繁工AI 本地解析工作台 - 配置
# 修改后重启服务生效。所有路径建议使用英文，避免编码问题。

import os

# ============ 基本 ============
HOST = "127.0.0.1"          # 只在本机访问；如需局域网访问改为 0.0.0.0
PORT = 8756                 # 端口，冲突可改
def _load_storage_config():
    """读取存储位置配置（storage_manager 写入的自定义路径）。"""
    try:
        import json
        _cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "storage_config.json")
        if os.path.exists(_cfg_path):
            with open(_cfg_path, "r", encoding="utf-8") as _f:
                return json.load(_f)
    except Exception:
        pass
    return {}

_STORAGE_CFG = _load_storage_config()
DATA_DIR = _STORAGE_CFG.get("data_root") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# ============ 文件夹扫描 ============
SCAN_INTERVAL_SEC = 30      # 文件夹自动扫描间隔（秒），0 = 关闭自动扫描
MAX_FILE_MB = 500           # 单个文件大小上限（MB），超过跳过并提示

# ============ 深度解析 ============
# 解析开关：False 时对应类型文件仅登记、不解析（标记 skipped）
# AUTO_DETECT_OPTIONAL=True 时：OCR/CAD 依赖一旦安装即自动启用（全套部署免改配置）；
# 依赖未装时按下方 PARSE_* 开关决定。想强制关闭某能力，把 AUTO_DETECT_OPTIONAL 设为 False 并保持开关 False。
AUTO_DETECT_OPTIONAL = True

PARSE_PDF = True            # PDF 文本/表格提取
PARSE_WORD = True           # Word (.docx) 文本+表格提取
PARSE_EXCEL = True          # Excel (.xlsx) 表格结构化（台账核心）
PARSE_TEXT = True           # txt/csv/md 等纯文本
PARSE_IMAGE = False         # 图片 OCR（需安装 PaddleOCR，见 requirements-ocr.txt）
PARSE_CAD = False           # CAD 图纸（需安装 ezdxf；DWG 需 ODA File Converter）
PARSE_PROJECT = True        # Project 计划（支持 .xml 格式；.mpp 请先用 MS Project 另存为 .xml）

# 支持的文件扩展名 → 解析器
EXT_PDF = [".pdf"]
EXT_WORD = [".docx"]
EXT_EXCEL = [".xlsx", ".xlsm"]
EXT_TEXT = [".txt", ".csv", ".md", ".log", ".json"]
EXT_IMAGE = [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]
EXT_CAD = [".dwg", ".dxf"]
EXT_PROJECT = [".xml"]      # Project 另存为的 XML（主计划文件）；也可 .mpp（需 Java+mpxj，暂缓）

# 设备位号正则（用于从文本/表格/图纸中识别设备，浅层实体提取）
EQUIPMENT_TAG_RE = r"(?<![A-Za-z0-9])(?!(?:GB|JB|HG|SH|DL|YS|SY|TB|QB|JG|JGJ|TJ|ZB|YD|SD|NB|MT|AQ|GA|FZ|QC|JT)\b/?)([A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])"

# ============ 可选依赖自动探测 ============
def _detect_optional():
    """探测 OCR / CAD 依赖是否已安装（全套部署后自动启用对应解析）。"""
    import importlib.util
    return {
        "ocr": importlib.util.find_spec("paddleocr") is not None,
        "cad": importlib.util.find_spec("ezdxf") is not None,
    }


OPTIONAL_READY = _detect_optional()

# ============ 向量化 ============
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # 中文通用，约470MB，首次运行自动下载
CHUNK_SIZE = 500            # 分块字符数
CHUNK_OVERLAP = 50          # 分块重叠

# ============ 云端合并（上传队列）============
# 云端主库服务地址（飞书托管地址的 API 前缀，或将来部署的云端服务）
# 留空 = 不上传，解析结果保存在本地 data/upload_queue/ 待命
CLOUD_ENDPOINT = ""
# 云端 API Key（云端服务上线后发放；留空则上传时忽略鉴权头）
CLOUD_API_KEY = ""
# 解析节点名称（多台电脑各自起名，云端合并时区分来源）
NODE_NAME = "我的电脑"
# 上传批次大小（每批文件数）
UPLOAD_BATCH_SIZE = 50

# ============ 平台级规范库（v0.1.10）============
# 国标/规范/通用文件独立建库，与子项目解析库分开；AI 检索项目库时可同时读取平台库。
PLATFORM_DIR = _STORAGE_CFG.get("platform_root") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "platform_data")
PLATFORM_CHECK_DAYS = 180        # 规范有效期检查周期（天）= 每 6 个月
PLATFORM_SEARCH_ENDPOINT = ""
STD_VERIFY_OPENSTD = True        # 是否允许访问全国标准信息公共服务平台核验（尽力而为）
STD_VERIFY_ON_UPLOAD = True      # 首次上传规范时立即核验是否过期（废止立即标注最新版）
AI_MODE = "local"                # AI 助手模式：local=离线检索+资料生成；gateway=接入 AI 网关联网问答
AI_GATEWAY_ENDPOINT = ""         # AI 网关端点（豆包/企业 Agent），POST {"query","context","history"} → {"answer"}
AI_GATEWAY_API_KEY = ""          # AI 网关鉴权
# v0.1.12：联网优化资料模板端点（预留）。配置后 docgen 生成时自动请求
# POST {"doc_type":..., "keywords":[...]} → {"template_hints":["..."]} 用于优化模板章节；
# 未配置时仅用本地解析库内容预填（设备清单/平台规范引用），不影响生成。
TEMPLATE_SEARCH_ENDPOINT = ""    # 联网核验/搜索最新版端点（预留：配置后 check-expiry 自动调用并替换，
                                 # 返回 {"标准号": {"status": "现行/废止", "latest_no": "GB/T XXXXX-2026"}}）

# ============ 其它 ============
LOG_FILE = os.path.join(DATA_DIR, "workbench.log")

# 手机语音转写（v0.1.26）：auto=本机装了 whisper/faster-whisper 则本地转写，
# gateway=调 AI 网关 /transcribe 接口；未装且未配置 → 待转写清单人工补录
VOICE_TRANSCRIBE_MODE = "auto"
VOICE_GATEWAY_ENDPOINT = ""
VOICE_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".amr", ".flac", ".wma", ".opus")

# ============ 版本号（v0.1.168）============
# 生成的资料页脚要写工具版本，原来 docgen.py 里写死 v0.1.30，
# 与实际版本差了一百多个小版本，交付的 Word 里版本号是错的。
# 统一由 config 提供，main.py 的 FastAPI version 与本常量保持一致。
# v0.1.181：分发包不再带 data/templates（运行期派生目录，122 条绝对路径泄漏 + 60MB 冗余）。
# 版本必须递增：包内容规则变了，WORKbuddy 要能按版本号区分「带模板库的旧包」与「首启重建的新包」。
# v0.1.182：修整卷聚合计数漏报 + 模板索引并发写丢失。
# ① 整卷拆车间后 generated/todo/skipped/通用表批次与逐车间合计对不上
#    （真实台账 19 车间：generated 36→33、skipped 2→0、tf_batch 36→2）；
# ② 3 路并发出卷时模板索引被「读—改—写」覆盖，12 个车间报「未找到模板」，
#    data/templates 堆出上万孤儿副本。
# v0.1.183：监理登记表里的表名没有对应模板时不再硬失败。
# ① 「设备安装记录」（SH/T3503-J302）直接借用现有「设备安装检查记录」的表出表
#    （用户 2026-10-31 决策）。之前会被子串匹配抢到「防爆电气设备安装记录」上。
# ② 模板库里完全没有的类别（签证、洽商、报审、监理自拟记录等）按国标通用格式落一份表，
#    并进待办清单「按国标通用格式生成」段；不再只留一行「未找到表类型」。
# ③ 兜底表按表种分列：检查/隐蔽/试验/签认/通用五类各自的列头与条款不同，
#    签证单不会被塞设备油漆检查项。
# v0.1.184：把「国标兜底表」和「借用表」在界面上说出来。
# 后端 v0.1.183 已经能出这两种表，但界面一个字段都没读：用户拿到文件不知道
# 这张是按国标通用格式凑的、也不知道借用了哪张表，监理问起来说不清。
# ① 单表结果：兜底表显示「⚠ 成功（国标通用格式）」+ 表号 + 条款数 + 空白表警告；
#    借用表显示「登记表写的是X，没有这张表的模板，已借用Y的表出记录」。
# ② 整卷结果：新增「复用现有表」「按国标通用格式生成」两行，并按登记项聚合 ——
#    不然一个登记项在 18 个车间会刷出 18 行一模一样的文字。
# v0.1.185：兜底表版面按表种分配列宽。
# 用 LibreOffice 真渲染出来看才发现的 —— 内容对不对（条款数、表种、表号）全对，
# 但版面是残的：四列一律 4.25cm 等宽，条款被挤在窄列里折成两三行，
# 后面两个**要手写**的列反而空着很宽，版面重心是反的；
# 第一次改完又把第 0 列压到 1.5cm，「分部分项工程名称」折成三行。
# 现在第 0 列 3.0cm（放得下 8 字标签），条款列最宽，手写列够写一行；
# 合并单元格的 tcW 按跨列求和、tblLayout 设 fixed，避免 Word 重新均分。
# v0.1.186：两处「验收链路」的缺陷修掉。
# ① tools/verify_install.py 的端口检查写死 8756，不读 app/config.py 的 PORT。
#    这个脚本自己提示「端口冲突就改 app/config.py 的 PORT」，用户照做了，
#    它却还盯 8756 —— 永远报「空闲」，这项检查等于白做。改成读配置，
#    并且不再是恒 SKIP（恒 SKIP 永远不会暴露问题）。
# ② 打包时漏排 tools/test_ledger_units_report.json —— 运行期产物随包发给别人。
#    排除清单是按名字逐个写的，漏一个名字就漏一份；打包回读改成按模式兜住。
# v0.1.192：整卷进度与「一键整卷」入口的四个真实缺陷（都是真浏览器 / 真数据实测出来的）。
# ① 进度字典无界增长：release_volume_slot 只把 running 置 False，从不删条目。
#    长期驻留单进程 = 慢性内存泄漏；界面上还分不清「刚跑完」和「三小时前跑完」。
#    改成两把刀：TTL 1800 秒（已结束只留 30 分钟）+ FIFO 上限 64 条。
#    淘汰顺序按**写入序号**而不是时间戳 —— 实测把时钟往回拨 2 小时后再开 3 个卷，
#    用时间戳排序会让 3 条刚跑完的记录被误淘汰 2 条、最老的旧记录反而被留下
#    （现场机器联网校时、用户手改系统时间都会造成时间戳非单调）。
# ② already_running 分支把按钮永久锁死：那条分支既不停轮询也不清 __volRunning，
#    而轮询在 !d.running 时又只是 return —— 两头都不收尾，用户只能刷新页面。
#    和 v0.1.190 修的「接口异常永久锁死」同源。
# ③ **「一键整卷」这条主路径在真实浏览器里从来没跑通过**：
#    getCurrentProjectIdForSup() 读的两条路都不存在 ——
#    localStorage 键 'fanGong_currentProject' 全仓只有读、没有写；DOM 里也没有
#    id='projectSelector' 的元素（真实下拉叫 projectSelect）。
#    函数恒返回空串 → runVolume() 一上来就 alert('请先在资源管理中选择项目') 然后 return。
#    册下拉填得再对，点下去也只会弹一个窗就结束。
# ④ get_volume_progress 的注释写「没有进行中的整卷时返回 None」，
#    实测整卷结束后仍返回一份 running=False 的残留字典，两套说法对不上。
#    统一为：从未跑过 → None；跑过 → 字典，判断是否在跑看 running 字段。
# v0.1.193：车间清单只认文件名 → 「资料生成」的车间下拉全是错选项。
# ① /api/workshops 只取 workshop_assign.list_by_workshop()，那是**文件级**归属。
#    设备台账是一份横跨全厂的汇总表，按文件名被整体归到「选矿厂」，
#    台账行里真实的 19 个车间从来没有进过清单。
#    实测真实项目 e75e857c：清单只有 1 项「选矿厂」，而下拉就是拿它去查设备预填的
#    —— 选中它 devices=0、missing 5 项；留空（全部车间）才是 60 台。
#    下拉里唯一的选项是错的，用户无从知道，生成的施工方案一个设备都没有。
# ② 现在把 index.json 里设备的 workshop 并入清单，并单独给出一份
#    docgen_workshops（= 台账里真有设备的车间）专供「资料生成」下拉。
#    文件级车间保留不动 —— 一份台账本来就是一整厂的文件，删掉会把已上传台账藏起来。
# ③ fieldtest「按车间预填」原来只断言 code==200，devices=0 也判 PASS —— 假绿灯，
#    已改成「台账有设备时预填必须真的取到设备」。同轮还修掉它两个自身缺陷：
#    脚本崩了仍打印「通过 N / 失败 0」，以及把 n_dev_idx 误写成 _n_dev_idx。
#
# v0.1.194（车间台账设备真正到达用户眼前）
# ① v0.1.193 修的是 /api/workshops，可那个卡片网格自 v0.1.157 起就被三级树取代、
#    一直是 display:none —— 用户实际看的「项目资料库」是 /api/files/tree，
#    它里面**仍然只有「选矿厂」一个节点**（文件名猜的），台账行内 19 个真实车间
#    一个都不显示。接口修了、用户眼前没变，等于没修。现在台账车间并入 tree 的 L2。
# ② 台账车间 file_count=0，点「批量管理」原来只甩一句「暂无文件」；
#    新增 /api/workshop/devices 取该车间台账设备，「中矿堆」实测 13 台。
# ③ 展开节点原来先输出「车间下无直接文件」，把设备说明顶掉（inner 已非空就不再追加），
#    有台账设备时不输出这句。
# ④ 这份真实台账 228 台设备**全部没有位号**，所以 L3 位号层天然为空，设备只能按
#    车间清单展示 —— 这不是缺陷，是台账格式决定的，界面上已写明原因。
# v0.1.195：两处修正，都出在「项目目录不可配置」这一个根因上。
#   ① app/project_manager.py 的 PROJECTS_ROOT / CURRENT_PROJECT_FILE 原来按
#      __file__ 推导，config.DATA_DIR 改了它们不跟着动 —— 用户把数据目录设到
#      D:\ 或装在只读目录时，项目照样往安装目录写，「数据目录可配置」对项目
#      管理失效，对可分发部署是硬伤。改为跟随 config.DATA_DIR。
#   ② 同一根因让 tools/test_gb_fallback.py 的 J 段（临时 DATA_DIR 起服务）
#      把自测项目写进了真实 data/，还把 current_project.json 指到这个空项目
#      且没还原 → 用户下次开程序看到的是空的「_j_节自测_xxxx」；同时 E 段
#      （project_id=None 走当前项目）断言数随当前项目漂移，189→188。
#      E 段改成临时项目根 + 显式 project_id，两个场景都跑，固定 7 条。
# v0.1.196：selftest 必须删掉自己建的测试项目，不能只切回当前项目。
#   实测事故：沙箱里累积到 87 个项目，其中 87 个匹配测试名前缀
#   （自测_ / 自测隔离_ / _j_节自测_ / 实测_ / 实测隔离_），72 个是
#   0 文件 0 设备的空壳。用户打开「选择项目」要在几十个空壳里找自己那个
#   工程。根因是 selftest 每次跑完只还原当前项目、不删测试项目，
#   而 phase3 的「竣工归档跨项目隔离」还会额外建一个「自测隔离_HHMMSS」。
#   改为记录本次运行创建的全部 id（CREATED_PIDS），跑完（含异常）逐个删除；
#   只删本次实际建出来的 id，绝不按名字前缀批量删（用户也可能建带「自测」的真项目）。
# v0.1.197：竣工清单的读改写必须原子化（并发 6 路实测丢 4 台）。
#   实测事故（真实项目 e75e857c，228 台设备，POST /api/completion-archive/all 69 秒）：
#   total_devices=222、failed_count=6，失败理由是
#     FileNotFoundError / PermissionError: ... completion_archive.json.tmp
#   根因两处：
#     ① _save_archive 用**固定名字**的 path+".tmp"，两个设备线程同时写时
#        A rename 走了 .tmp，B 再 rename 就报「不存在」；Windows 上 A 还持有
#        句柄时 B 直接 PermissionError —— 这是现场「一键竣工偶尔少几台」的来源。
#     ② 每台设备都做一次「读全量 → 改一条 → 写全量」，228 台 = 228 次全量往返；
#        且读改写没有锁，后写的线程用旧快照整份覆盖，前面刚写进去的设备凭空消失
#        （实测 6 路并发最终只剩 2 条）。
#   改为 uuid 临时名 + 模块级可重入锁 + _update_archive 原子入口；
#   批量接口(_all)只读一次、只写一次，不再逐台落盘。
APP_VERSION = "0.1.197"

# ============ 本地配置覆盖机制（v0.1.127）============
# 若存在 app/config.local.py（由自动更新模块在检测到本地修改时生成，或用户手工创建），
# 程序启动时用其中的配置覆盖本文件默认值（如 HOST="0.0.0.0" 等）。
# 这样自动更新覆盖 config.py 时不会丢失用户的本地化设置。
try:
    _cfg_local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.py")
    if os.path.isfile(_cfg_local):
        _local_ns = {}
        with open(_cfg_local, "r", encoding="utf-8") as _f:
            exec(compile(_f.read(), _cfg_local, "exec"), _local_ns)
        for _k, _v in _local_ns.items():
            if not _k.startswith("__") and _k.isupper():
                globals()[_k] = _v
except Exception:
    pass
