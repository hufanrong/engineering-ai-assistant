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
# v0.1.224：PDF 无文本层时是否用 OCR 兜底（默认开）。
# 与 PARSE_IMAGE 分开：那个开关管「用户直接传 jpg/png」，
# 这里管「PDF 里根本没有文字层」（CAD 直接打印的图形 PDF）。
# 现场实测：马诺诺 30 份 PDF 里 16 份是这种，原文一个字都提不出来。
PDF_OCR_FALLBACK = True
PARSE_CAD = False           # CAD 图纸（需安装 ezdxf；DWG 需 ODA File Converter）
PARSE_PROJECT = True        # Project 计划（支持 .xml 格式；.mpp 请先用 MS Project 另存为 .xml）

# 支持的文件扩展名 → 解析器
EXT_PDF = [".pdf"]
EXT_WORD = [".docx"]
EXT_EXCEL = [".xlsx", ".xlsm"]
# v0.1.224：.xls（Excel 97-2003）单独列出，不复用 EXT_EXCEL ——
# 凡是拿 EXT_EXCEL 判断「能用 openpyxl 读」的地方都不该被 .xls 命中。
# 解析分派在 parsers/engines.py::_pick_parser 里显式走 parse_xls（xlrd）。
# 现场实测：马诺诺项目一批 62 个文件里 3 个 .xls（斗提机表、两家箱单）
# 上传后彻底消失，就是因为这里不认。
EXT_EXCEL_LEGACY = [".xls"]
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
# v0.1.198：把 v0.1.197 的「整份 JSON 读改写」缺陷在另外两处一并扫掉。
#   同一缺陷模式横向排查，又找到两个高频写盘点，都跟竣工清单同一根因：
#   ① app/scanner.py::_save_index —— 资料库索引（用户全部已入库文件清单）
#      原来 open(path,"w") 直接覆盖写。实测：2000 条 / 121831 B 的索引，
#      写到第 4075 行附近中断 → 文件剩 60915 B 半截 JSON，json.load 抛
#      JSONDecodeError: Unterminated string，而 _load_index 的 except 把
#      异常吞成 {} → 用户整个资料库索引（含已解析文件、向量、标签）全部消失，
#      但上传的原始文件还在，表现为「入库了一堆文件，列表却是空的」。
#      改为 uuid 临时名 + os.fsync + os.replace 原子替换 + 模块级可重入锁；
#      实测同样中断后仍是 121831 B、完整 2000 条。
#   ② app/upload_queue.py::_save_idx —— 上传队列的 sha256 去重索引。
#      原来 tmp 名固定为 path+".tmp"，并发上传时互相踩踏；且 except 只 pass，
#      写盘失败连一行日志都没有，后果是去重索引悄悄失效（同一文件反复入队、
#      反复解析）。实测反向验证：并发入队刷出
#        [Errno 2] No such file or directory: .../_sha_index.json.tmp
#      而正常实现下 20 路并发「0 错误 / 索引 20 条 / 队列包 20 个 / 无残留 tmp」。
#      改为 uuid 临时名 + 可重入锁 + 失败留痕；enqueue 的「查重—建包—写索引」
#      整体进锁（_enqueue_locked），避免两个线程同时判定「没传过」。
# v0.1.199：把「原子写」收成一个唯一实现，全仓库统一调用（不再逐模块抄）。
# v0.1.200：业务数据项目隔离收成一个实现（app/project_scope.py）。
#   实测缺陷：construction_logs / doc_relations / docplan_tasks / equipment_merge /
#   piping_network / rejected_candidates / tag_alias / version_map 这 8 个业务文件
#   全写进全局 data/，且路径是模块级常量或 lazy-init 常量——① 项目 A 的数据出现在
#   项目 B；② 切项目后常量不复算，仍写旧路径（与 v0.1.195 的 PROJECTS_ROOT 事故同源）。
#   证据：projects/ 下 91 个项目目录里这 8 个文件一个都没有，而全局 data/ 的
#   version_map.json 躺着 12 个文件名 / 200+ 条版本记录，不属于任何项目。
#   v0.1.197/v0.1.198 连着修了三处同源缺陷，说明问题不在某个模块写错，
#   而在「每个模块自己写一遍落盘逻辑」这种结构 —— 只要还分散着，
#   下次新增模块照样会重犯。所以新增 app/atomic_io.py：
#       write_json(path, obj, indent)  唯一原子写实现
#       path_lock(path)                读改写要用的同一把锁
#       read_json(path, default)       读失败留痕（不再无声兜底成 {}）
#       sweep_orphan_tmp(root)         启动时清扫历史遗留临时文件
#   全仓 69 处「直接 open(...,"w") 写最终文件 + json.dump」全部换成 write_json，
#   涉及 50 个模块（设备台账/资料库索引/施工日志/隐蔽验收/方案清单/
#   上传队列/关系图/空间模型/项目元数据/模板索引…）。语义完全不变：
#   indent 与原样一致、返回行为不变、异常照旧向上抛。
#
#   顺带查到一个真实现场问题：equipment_merge 手写 mkstemp 却没在异常里
#   清理临时文件。实测 data/projects/e75e857c/ 下积了 3 个 index.*.tmp，
#   每个 127304 B、各存一份完整的 228 台设备索引（11-02 的三个时间点），
#   白占 380 KB 并把设备数据在用户目录里重复了三份。改为 write_json，
#   并在 run() 启动时调 sweep_orphan_tmp 自愈用户机器上已有的历史垃圾
#   （实测已清除 3 个，228 台设备数据完好、coverage=1.0）。
#
# ============ v0.1.201 「资料生成」全链路假成功 + 产出丢失 ============
# 用户点「智能生成资料」看到「生成成功」，去「生成历史」却是空的、下载报
# 「文件不存在」、重新生成还把类型认错。逐层查出 7 处缺陷，全部实测复现后修掉：
#
#   A 报成功却没文件：前端下拉 11 个类型，8 个返回 ok=true success=1，
#     但项目 generated_docs 下的 docx 数量 14 → 14 没变；另 3 个返回 failed。
#     根因：_call_generator 调 mining_* 系列只返回 JSON 结构（plan/sections），
#     没有任何一步写文件；else 分支返回 status="template_generated" 占位串；
#     main.py 把「函数没抛异常」当成成功。修法：新增 _persist_docx() 落盘层，
#     并把「persisted && output_path」作为唯一成功判据。
#
#   B 历史恒为空：GET /api/smart-doc/history 返回 ok:true history:[]，而磁盘上
#     有 14 份真文件。根因：v0.1.168 把产出从全局 data/generated_docs（平铺）
#     改到 <项目>/generated_docs/<类型>/（嵌套），读接口一直没跟着改。
#     修法：改走 archive._list_generated()，与写真源同一处。
#
#   C 下载恒报「文件不存在」：同上，读的是不存在的平铺全局目录。
#     修法：改按 <项目>/generated_docs 解析，并加目录穿越校验
#     （abspath 必须落在 gen_root 内）。
#
#   D 再生成把类型认错：繁工AI_施工方案_20261104_192947.docx 被按 "_" 切，
#     切成 file_type="繁工AI"、device="施工方案"。
#     修法：doc_type 从父目录名取，文件名只用于展示。
#
#   E 同秒生成互相覆盖（测试跑出来才发现的）：文件名精确到秒
#     （%Y%m%d_%H%M%S），批量生成 30 台设备必然同秒。实测连续 5 次
#     _save_generated 只留 1 个文件，其余 4 份被覆盖。
#     修法：基础名已存在则加 _2/_3 序号后缀；复测 5 次得 5 个不同文件。
#
#   F 两处产出根目录各写一半：按用户规则「有现表用现表」，表单类走
#     supervision_templates.render_gb_fallback() 落在 <项目>/exports/，
#     方案类走 docgen 落在 <项目>/generated_docs/。exports 里的那些
#     对「生成历史」「下载」全部不可见。
#     修法：把 exports 产物读成字节后重存进 generated_docs/<归档类型>/，
#     再删掉 exports 副本，全项目只留一处产出真源。
#
#   G 内部短名漏到归档目录：用户选的是「设备验收记录」，归档目录却叫
#     「设备验收」，历史里对不上用户认得的表名。
#     修法：_ARCHIVE_TYPE 映射成用户可识别的表全名（开箱检验→开箱验收记录、
#     隐蔽工程→隐蔽工程验收记录、设备验收/安装记录→设备安装检查记录、
#     基础验收→设备安装基础复测记录、试运转→单机无负荷试运转记录、
#     安全交底→安全技术交底记录、焊接方案→焊接作业指导书），
#     与 docgen / 竣工组卷 VOLUMES 04 卷同名处保持同名。
#
# 回归测试 tools/test_smart_doc_persist.py 覆盖 A-F 六组，62 项断言。
# 反向验证过两次（把缺陷注回去看测试是否真的报红）：
#   注入「无落盘」→ 11 个类型的「产出文件」「是合法 docx」断言全部 FAIL；
#   注入「同秒覆盖」→ [D] 组「连续 5 次落盘得到 5 个不同文件名」FAIL
#   （实测不同=1）。两次注入后即恢复，最终 62 PASS / 0 FAIL。
#
# ============================================================
# v0.1.202：按用户规则「首次在本地电脑实测」前，拿紫金选矿厂真实台账
# （data/uploads 真实设备台账，228 行 / 215 行有设备名 / 19 个车间）
# 把整条链路真跑了一遍，又打出 4 个真实缺陷 —— 全部是「界面点得动、
# 真实数据下出不来能用的表」这一类，空数据测试绝对看不出来：
#
#   H 设备识别只认 8 类硬编码设备名，真实台账命中率 6.5%。
#     实测 14/215 命中，未命中「Y0#胶带输送机」「金属探测器」
#     「重型板式给料机」「液下渣浆泵」「电动单梁起重机」这些最常见的。
#     更糟的是把设备名**改写成别的设备**：圆锥破碎机→颚式破碎机、
#     高压辊磨机变频器→球磨机、真空带式过滤机→压滤机。给监理的表上
#     印着另一台设备的名字，属于不可交付的错误。
#     修法：以项目台账为权威设备名单做精确命中（原名原样返回），
#     内置名单只整词命中，别名加冲突词拦截；认不出时用用户自己写在
#     「：」后面的设备原名（那是用户提供的事实，不是编造）。
#     复测：215/215 原样识别（100%），改写 0 起。
#
#   I 按设备批量出表，设备列全空、三份表内容完全相同。
#     _persist_docx 的表单分支从不把 equipment 传给
#     render_gb_fallback，后者也没有接受单台设备的入口，只按车间查台账。
#     实测球磨机1/2/3 → 3 份字节级不同的文件，但「设备名称」「设备位号」
#     两列全空、内容一致，用户分不出哪份是哪台设备的。
#     修法：render_gb_fallback 新增 devices 参数；落盘层按名称从台账补全
#     位号与规格型号再传下去。复测 3 台设备 → 3 份互不相同（sha 全不同）、
#     每份都含自己的设备名。
#
#   J 资料-设备关联一条都没登记成功，且**异常被静默吞掉**。
#     archive._save_generated → doc_relations.register_doc 内部做
#     set(devices)，而传进来的是 {"tag": ...} 这种 dict，dict 不可哈希 →
#     TypeError；外层 try/except 把异常吞掉，界面一切正常。
#     实测当前项目 10 份生成文件 relations.json 里 with_devices=0，
#     「按设备找资料」「完整性检查」全部失效。
#     修法：register_doc 自身归一化输入（dict → 位号字符串），
#     _save_generated 同样先归一，并把失败原因打到日志不再无声无息；
#     表单分支落盘时也补传设备。复测 3 份表 with_devices=3。
#
#   K 前端「批量生成」在真实数据下**完全不可用**，选设备框永远为空。
#     GET /api/devices 读 workshop_assign.list_by_workshop() 的
#     ws_data.get("workshops")，但该函数返回的是 {车间: [记录]}，
#     顶层**没有 workshops 这个键**，取出来恒为 None，循环体一次不执行；
#     另算出来的 dw_data 根本没被使用。
#     实测真实项目（228 台设备）无论传不传车间都返回 devices=[]。
#     修法：改为以项目设备台账为主源（带名称/型号/车间），车间归属登记
#     只作补充；无位号时 value 回落设备名称（真实台账 215/228 位号为空）。
#     复测：全部车间 125 台、磨浮车间 21 台。
#
#   L 再生成丢掉设备名。regenerate_by_type 的 equipment 缺省为空，
#     实测对「设备安装检查记录」点再生成，新表「设备名称」列是空的。
#     修法：按 doc_id 从 doc_relations 取回原设备名再生成；端点把原文件
#     的 id 传下去。复测：再生成后设备名称行=溢流型球磨机。
#
# 回归测试 tools/test_smart_doc_persist.py 扩到 A-I 九组，
# 新增 [H] 设备识别（真实台账口径）/ [I] 按设备出表不串台。
#
#   M 批量生成模块「选择车间」下拉从来没人填充。页面里只有一个
#     <option value="">全部车间</option>，而 loadBatchDevices() 在车间为空时
#     直接 return —— 两头一夹，用户在批量生成模块里**永远看不到一台设备**。
#     实测当前项目 /api/devices 有 125 台可用，页面却一直显示
#     「请先选择车间加载设备列表」，这个模块在真实数据下等于空的。
#     （顺带更正一处自测口径：本模块下拉里只有 设备验收记录/开箱检验记录/
#     隐蔽工程验收记录/安全技术交底/技术交底 五个值；「设备安装检查记录」
#     是归档名不是下拉值，拿它当入参测出来的失败不算产品缺陷。）
#     修法：从 /api/workshops 填充车间（带台数），初始化即加载一次设备；
#     车间留空按「全部车间」加载，不再直接 return。
#
#   N /api/devices 把同名设备折叠后不给任何提示。磨浮车间台账 30 台，
#     其中 渣浆泵×3、充气式机械浮选机×3、液下渣浆泵×3、浮选配套刮板×2、
#     电动葫芦×2、泡沫泵×2（台账本身没有位号），按 tag|name 去重后只剩 21 条。
#     用户看到 21 台会以为台账丢了一半。
#     修法：折叠时累加 same_name_count，前端标注「同名 N 台」，不吞数据。
#
#   O 首屏资源管理是空的（v0.1.204，真实浏览器实测发现）。页面默认停在
#     module-resource，但 DOMContentLoaded 只调 loadProjects()，
#     **从来没人调 loadResourceData()**；switchModule('resource') 里虽然有
#     loadResourceData()，但那只在用户主动点页签时才执行。
#     实测（Chromium headless，项目 322fef90 有 228 台设备/20 个车间）：
#       首屏 statFiles/statWorkshops/statDevices = 0/0/0，车间卡片 0 张，
#       导出车间下拉 0 项 —— 用户看到的是「项目是空的」；
#       手动点一下「资源管理」页签后变成 1/20/21、20 张卡片。
#     修法：拿到当前项目后立刻调 loadResourceData()。
#
#   P 导出卡片「选择车间」的显隐从来没生效过（v0.1.204）。
#     <div style="flex:1" id="exportWorkshopWrap" style="display:none">
#     写了两个 style 属性，按 HTML 规范只认第一个，display:none 被丢弃，
#     元素一直是显示状态；代码里也没有第二处去切换它。
#     修法：合并成一个 style 属性 + syncExportWorkshopWrap() 按导出范围切换，
#     并给 exportScope 绑 onchange。
#
#   ⚠ 自测口径教训（必须延续）：本轮 3 次「发现缺陷」都是我的测试错的，
#     不是产品错 —— ① 在空项目上问车间/设备数返回 0 是正确行为；
#     ② 固定 sleep 猜异步时长（/api/supervision-templates 实测耗时 2.38s，
#        600/900/1200ms 的等待都读到了「加载中」中间态，被误报成空下拉）；
#     ③ DOM 桩的 appendChild 没有同步更新 innerHTML，断言永远读到 0。
#     结论：断言前必须先确认真实数据存在、异步真的落定，再判缺陷。
#
# ============ v0.1.205：智能窗口（module-ai）逐项实测 ============
# 上一轮把首屏/资料生成验完了，这一轮改验「智能窗口」——
# 紫金矿业的工程师实际就是在这个窗口里问「磨浮车间有哪些设备」的。
#
#   Q 智能窗口的提问从来没真正调用过后端（v0.1.205，真实浏览器实测发现）。
#     sendChat() 里根本没有 fetch，只有一段关键词匹配 switchModuleByName()，
#     欢迎语却写着「或直接提问工程相关问题」—— 用户问任何问题都只得到一句
#     「已为您跳转到XX模块」。测试办法：monkey-patch window.fetch 计数，
#     实测请求数 = 0。
#     修法：真的 POST /api/ai/chat，渲染 answer / sources / 文档下载按钮。
#
#   R AI 检索硬编码全局向量库，检索不到当前项目的资料（v0.1.205）。
#     ai_chat._store() 写死 config.DATA_DIR/'vectordb'，而项目隔离约定
#     （app/project_scope.py）要求业务数据一律落在 data/projects/<id>/ 下。
#     实测项目 322fef90 有 228 台设备，问「磨浮车间有哪些设备」，
#     返回 sources.project = 0 —— 全局 data/vectordb 目录压根不存在。
#     修法：按当前项目取 <项目数据目录>/vector_db。
#
#   S 向量库不可用时没有任何降级，检索恒为 0（v0.1.205）。
#     离线单机环境没装 chromadb，_store().search() 抛
#     ModuleNotFoundError 被 try 吞掉，结果一条不返回还不报错。
#     修法：降级走 vector_store.search_keyword()（直接匹配 parsed_cache/*.json），
#     并在回答里如实写明「本次按关键词匹配检索，未使用向量语义检索」。
#
#   T 待办列表取错字段名，整列渲染成空（v0.1.205）。
#     代码读 p['name'] / p['missing_summary']，而 plan 数据里是
#     doc_type / desc / missing —— 实测 9 条待办全部显示为「  - ：资料不全」。
#     修法：改读正确字段，缺资料时拼「缺 X、Y」。
#
#   U 6 个「快捷功能入口」全是 alert('……请到XX中查看') 文字占位（v0.1.205）。
#     后端接口其实都存在（/api/search、/api/relations、/api/spatial/structure、
#     /api/platform/list、/api/equipment-merge/pending、/api/projects/backups），
#     用户点进去只得到一句「请去别的页面看」—— 功能等于不存在。
#     修法：统一弹窗承接真实数据；接口报错时如实显示错误，不假装成功。
#
#   V 云端合并的「扫描」按钮打到了不存在的路由（v0.1.205）。
#     前端 POST /api/equipment-merge/scan，实测 404 {"detail":"Not Found"}；
#     真正的执行入口是 POST /api/equipment-merge/run（无 body），
#     返回汇总计数（total_equipment / merged_count / pending_count /
#     duplicate_removed / skipped_rows）而不是 items 数组。
#     修法：改打真实路由并按计数渲染。
#
#   ⚠ 自测口径教训（必须延续）：本轮我自己的测试也犯了两次错，
#     都是「把测试写错当成产品有缺陷」，已修正并留下证据：
#     ① 查 /api/supervision/status 忘了带 book 参数，返回 total:0 就报警
#        —— 实际带上 book=第一册&workshop=磨浮车间 后是 total:6、generated:6。
#     ② verify_archive.js 里断言了一个根本不返回的字段 page_basis，
#        却把 undefined 硬写成 true —— 假通过。
#        已改为：从落盘的 _卷内目录.docx 抠出「本卷共 N 份文件，合计 M 页」，
#        再用 _safe_page_count 独立重渲 6 个 docx 复算页数并对账。
#
# ============ v0.1.206：「检查更新」恒返回 0.0.0 ============
# WORKbuddy 在本机实测通过（53/0/0，Windows 11，D:\fangong-workbench）后，
# 我在沙箱里顺手把两个此前从未被测过的模块跑了一遍，抓到这个问题：
#
#   W 检查更新功能形同虚设（v0.1.206）。
#     实测同一时刻两个接口对「当前版本」给出不同答案：
#       /api/status        -> version=0.1.205   （对）
#       /api/update/check  -> current_version=0.0.0（错）
#     并且 latest_version 也是 0.0.0、has_update=false —— 用户永远看到
#     「当前已是最新版本」，即使远端真有新版也检测不出来。
#
#     根因两条取值路径全部打空（auto_updater.get_current_version）：
#       1) 读 config.VERSION —— config.py 里没有这个属性，真名是 APP_VERSION；
#       2) 回退读 main.py 里的 `version = "..."` —— main.py 没有这种写法。
#     于是落到末尾 return "0.0.0"。
#
#     远端版本那边同样错：raw 方式去 main.py 找版本号（找不到），
#     API 兜底靠提交信息里的 `vX.Y.Z` —— WORKbuddy 的提交是
#     "test(workbuddy): 20261106_080711 status=passed"，没有版本号，
#     于是 latest_version 也变成 0.0.0。
#
#     修法：当前版本读 config.APP_VERSION（兼容旧名），再兜底解析
#           config.py 源码；远端版本改读远端 config.py 的 APP_VERSION。
#
# v0.1.207：v0.1.206 只修了「当前版本」，远端那半边没修透，实测抓到：
#     本机 0.1.206 已推到 main 后，连续 5 次 /api/update/check 得到
#       第 1~3 次：latest=0.1.205  source=api
#       第 4~5 次：latest=0.1.206  source=raw
#     同一接口、同一件事，几秒内两个答案。两个独立根因：
#       1) raw 路径在沙箱网络下约一半返回 502（连续 6 次：OK/502/OK/OK/OK/502/502），
#          单发一次就掉到 API 兜底；
#       2) API 兜底仍用提交信息里的 `vX.Y.Z` 猜版本号，而 v0.1.206 的提交
#          沿用了上一版文案 "feat(v0.1.205): ..."，于是抓到 0.1.205。
#     修法：raw 加两次重试（3 次机会）；API 兜底改从 contents API 取
#           config.py 原文再读 APP_VERSION，与 raw 同一数据源；
#           两者都取不到时明确返回 ok=false 报错，绝不拿猜的值冒充。
# v0.1.208：上传队列口径不一致，索引文件被当成待上传包。
#     实测（2026-11-06，项目 322fef90 的 upload_queue 目录）：
#       目录实际内容 = 1 个真包 + 内部索引 _sha_index.json
#       pending_count() = 2        （错，把索引算进去）
#       list_pending()  = 1 条     （对）
#     同一队列、同一时刻两个接口给出不同答案；/api/status 的 queue_pending
#     就是这个 pending_count —— WORKbuddy 本机报告 queue_pending: 3，
#     同样是「2 个真包 + 索引」被算成 3。
#     危害不止计数：
#       · upload_all 会把 _sha_index.json 当包读，payload['payload'] 直接
#         KeyError，被记进「上传失败」→ 用户看到「1 成功 1 失败」，
#         而失败的那一条根本不存在；
#       · clear_all 会把索引一起删掉，索引丢了下次入队要全量扫队列，
#         正是 v0.1.177 修过的 O(n²) 假死场景；
#       · remove_packages 若被传入索引名也会删掉它。
#     修法：抽 _queue_files() 统一过滤（排除以 `_` 开头的内部文件），
#           pending_count / list_pending / upload_all / clear_all /
#           remove_packages 全部走它，口径只有一个。
#
# v0.1.209 ——「已入库文件数」同一个事实两个答案
#     实测（2026-11-07，项目 322fef90，索引顶层 6 个键）：
#       keys = files / devices / workshops / <一个 sha256> /
#              ledger_skipped_rows / updated_at
#       GET /api/status  indexed_files  → 6      （错，数的是顶层键数）
#       GET /api/files   条目数          → 1      （对）
#       真实已入库文件                    → 1 个（设备台账_真实_选矿厂.xlsx）
#     6 对 1。WORKbuddy 本机报告里 indexed_files: 6 也是这个假数。
#     同一处错误还藏在项目导入（project_backup）：它写
#       len(idx["files"]) if isinstance(idx["files"], list) else len(idx)
#     项目初始化后 files 恒为空列表 → 永远走 len(idx) 分支 → 导入完统计栏
#     直接显示错的文件数；files 非空时又漏掉扁平 {sha: info} 写入的条目。
#     修法：scanner 新增 count_index_files()，口径 = files 列表条目 +
#     顶层 sha 形键条目（去重），剔除 INDEX_RESERVED_KEYS 与新增的
#     INDEX_AUX_KEYS（ledger_skipped_rows 这类非文件辅助键）；
#     /api/status 与 project_backup 统计统一调它。
#
# v0.1.210 —— 把「同一事实两个答案」挡在本地实测阶段
#     v0.1.206~209 修的四个缺陷（版本号、待上传数、已入库文件数）有一个共性：
#     每个接口单独看都返回 ok:true、界面点着也像正常，只有把**同一时刻的两个
#     来源**摆在一起比才露馅。这类缺陷靠人工点界面永远发现不了 ——
#     WORKbuddy 上一轮报告 53 项全过，可它同一份报告里 queue_pending=3、
#     indexed_files=6 两个数字本身就是错的；它没有「交叉比对」这项断言。
#     改动：tools/selftest.py 新增阶段⑥「同一事实交叉比对」，8 项断言成对比较
#       /api/status.version        vs /api/update/check.current_version
#       /api/status.queue_pending  vs /api/queue.pending vs len(queue.items)
#       /api/status.indexed_files  vs /api/files.total vs len(files.files)
#       /api/relations.devices     vs relations.stats.devices vs spatial.structure
#       /api/projects.total        vs len(projects)
#     本阶段全部只读（有 153 条写路由，其中 /api/queue/clear 会真删数据）。
#     反向验证：把 indexed_files 改回 len(_load_index()) → status=6 而列表=1，
#     阶段⑥报 FAIL、exit=1；把 _queue_files 改回 endswith(".json") →
#     status=2 api=2 items=1，同样 FAIL、exit=1。两处回退都被抓住。
# v0.1.219 —— 「只能备份，不能恢复」：一个 422 加一个不存在的按钮
#     从用户入口走，而不是只在模块层验，才暴露出来。两处缺陷叠加：
#     ① 后端签名错：`@app.post("/api/projects/import")` 下写的是
#          async def import_project(request):
#        缺少 `: Request` 类型标注。FastAPI 因此把 request 当成**必填 query 参数**，
#        请求根本没进函数体就被拒。实测（2026-11-09，真实 HTTP）：
#          POST /api/projects/import  →  422
#          {"detail":[{"type":"missing","loc":["query","request"],
#                      "msg":"Field required","input":null}]}
#        同一文件里另外 4 个函数都写的是 `request: Request`，只有这一处漏了。
#        也就是说「从备份恢复项目」这个接口自 v0.1.110 写下起，
#        **一次都没有成功执行过**，而 /openapi.json 里它一直都在。
#     ② 前端没有入口：web/index.html 里 grep "fgbak" = 0 处，
#        grep "importProject|restoreProject|projects/import|恢复项目|导入项目" 无结果；
#        备份面板只有「💾 立即备份当前项目」一个按钮。
#        用户能备份、却没有任何办法从备份恢复。
#     修法（三处）：
#       1) main.py 补 `: Request` 标注；
#       2) index.html 备份面板新增 .fgbak 文件选择 + 新项目名 + 「↩ 恢复为项目」，
#          只有后端 ok:true 才显示成功并报出真实文件数，失败原样回显后端错误，
#          成功后调 loadProjects() 真刷新列表（不假装成功）；
#       3) project_backup 解压时跳过包内 project_meta.json —— 那份记的是**源项目**
#          id/name/created_at。实测恢复成新项目后，目录名是新 id、meta 里仍是旧 id
#          → /api/projects 出现两条同 id 项目（11 项里 322fef90 两次），
#          前端下拉两个 option 同 value，用户选不中新项目；覆盖模式还会把目标
#          项目的 id/name/created_at 一起改掉。项目身份以目标项目为准。
#     验证（真实 HTTP，不是只跑模块层）：
#       修前 E1-E3 通过、导入 422 失败；补签名后 I1-I3/I5 通过、I4 报「恢复的项目
#       不在列表」；再补 meta 跳过后 8 项全 PASS（导出 86 文件 / 包内 22 份成果
#       与磁盘 22 份一致 / 恢复后逐字节一致 / 历史 22 条可读）。
#       测试用完即删（删新项目目录 + 备份文件），并把审计流水按字节边界回滚，
#       用户真实项目回到基线：339 行 / md5 7f7c3bd1 / 10 个项目 / 指针 322fef90。
#     阶段⑥新增 6.16 源码契约：路由签名 + 前端入口同时成立，否则报红。

# v0.1.220 —— 把「路由签名缺类型标注」从单点补漏升级为全量门禁
#     上一轮只修了 import_project 一个签名。本轮做了全项目 AST 扫描，确认
#     「`async def f(request)` 少写 `: Request`」这类缺陷**当前 0 处**，
#     但它有极强的隐蔽性：/openapi.json 里路由照旧列着、页面也无异常，只有真实
#     调用才会 422，而且函数体一次都不执行 —— 等同于「接口存在 ≠ 接口能用」。
#     单点防守挡不住下一次同类写法，因此新增 tools/check_route_signatures.py：
#       遍历 app/ 下全部 py 文件，找出所有带 @app.get/post/put/delete/patch 等
#       装饰器的函数，逐个参数检查注解；无注解即报出「文件:行号 函数名(参数)」。
#     该脚本自身踩过一个假通过：它放在 tools/ 下却按 __file__ 同级找 app/，
#     于是扫到 0 个路由、还 rc=0 报「没有问题」。现在目录解析改成项目根 +
#     一条硬门禁「路由数为 0 即 rc=1」——零命中不等于无缺陷。
#     实测：扫描 92 个 py 文件，识别路由函数 441 个，缺标注参数 0 个，rc=0；
#     反向验证（临时造一个 def bad(request) 的路由）→ 门禁报红 rc=1。
#     阶段⑥新增 6.17：调用该脚本，退出码 0 且汇总含「缺标注参数 0 个」才算通过。
#     另一件事：上一轮新增的「从备份恢复」入口只用 grep 验过源码，没在浏览器里
#     点过。本轮用本机 Chromium + DevTools Protocol 真开页面、真点击、真读 DOM，
#     走用户真实路径（顶部导航「智能窗口」→ 快捷入口「项目备份」→ 备份面板）：
#       P0 页面可开 / P1 入口可见 / P2 文件选择框是 type=file 且 accept 含 .fgbak
#       P3 「恢复为项目」按钮在真实 DOM 且可见
#       P4 不选文件点恢复 → 提示「请先选择」，且对 /api/projects/import 的请求数 = 0
#       P5 此时不得出现「已恢复」 / P6 空 FormData 返回 HTTP 200（不是 422）
#       P7 塞入损坏 .fgbak 点恢复 → 真实上传、import 请求数 = 1、显示
#          「恢复失败：读取备份文件失败：File is not a zip file」、不假报成功
#       P8 loadProjects 存在且 /api/projects 可读（10 个项目）
#       P9 无未捕获 JS 异常
#     结果 10 PASS / 0 FAIL，rc=0。验证只读：用空表单与垃圾字节，不建项目、不写备份。
#     跑完独立核对用户真实数据未被动过：审计 339 行 / md5 7f7c3bd1 / 10 个项目目录 /
#     0 个备份 / 指针 322fef90 / 322fef90 的 docx 73 份。

# v0.1.221 —— 自测不能把垃圾写进用户真实项目；只读接口不能改项目元数据
#     本轮不是按计划挑活，是巡检出来的两个实测缺陷。
#
#     缺陷一：`tools/test_gb_fallback.py` 的 [D] 段传 `project_id=None`，
#     而 `render_gb_fallback` 里的 `_pm.get_project_data_dir(None)` 会回落到
#     **当前项目**（= 用户真实项目）。后果：每跑一次该脚本就往
#     322fef90/exports/ 里多一份「完全不存在的表XYZ_全厂_<时间戳>.docx」。
#     真实项目里已攒了 19 份这种垃圾，时间戳与自测轮次一一对应
#     （11-06 07:05 / 11-06 19:07 / 11-07 01:07 / … / 11-08 07:15）。
#     而脚本自己 rc=0、192 条断言全绿 —— 断言只查「文件落盘了没」，
#     从没查「落在谁家的目录里」。用户 2026-11-06 提的「空测项目清理」
#     之所以一直清不干净，根源之一就是每次自测又往里添东西。
#     修法：临时项目根 + 显式 project_id（与 [E] 段同一写法），并新增一条
#     守卫断言「产出落在临时项目目录内」——把后台改回 None 立刻报红。
#     实测：修复后 193 passed / 0 failed；真实项目新增 0 个文件。
#     反向验证：把 project_id 改回 None → 「产出落在临时项目目录内」报红、rc=1，
#     并当场在真实项目里出现一份 完全不存在的表XYZ_全厂_20261110_011411.docx
#     （已删除，删后与开工快照逐文件 sha256 比对：新增 0 / 消失 0）。
#
#     缺陷二（产品缺陷，不是测试缺陷）：`GET /api/projects/current` 是只读接口
#     （打开页面就调），却经 `_refresh_project_stats` → `update_project_stats`
#     **无条件写盘并刷新 updated_at**。字节级证据：
#       md5 a02e757d6ad9761221084a9107b324cd  updated_at=2026-11-10 01:12:22
#       → 只调一次 GET /api/projects/current
#       md5 e14438041e2e5edd6488c3b96d7ce38a  updated_at=2026-11-10 01:15:16
#     也就是「什么都没做、只是打开看了一眼」就改掉了工程的最后修改时间。
#     危害不止显示：`_pick_successor_project()` 用 updated_at 挑「最近动过的项目」
#     当删除后的接任者，看一眼就能改掉接任顺序。属于本项目反复出现的
#     「同一件事两个答案」——界面说刚更新过，磁盘上没有任何实际变化。
#     修法：update_project_stats 逐字段比对，只在真的变了才写盘、才刷 updated_at；
#     返回值加 changed 供调用方判据；全 None 视为「没变」。
#     新增 tools/test_readonly_no_write.py（17 条断言，含独立进程起真服务、
#     真发 HTTP 请求验证接口层），阶段⑥新增 6.18 调它。
#     反向验证：把 update_project_stats 改回旧的无条件写盘 → 12 passed / 5 failed、
#     rc=1。这里踩过一个假通过并已修：第一版 D 段在同一秒内比对 md5，
#     updated_at 秒级精度、写回值字符全等，于是旧实现照样 PASS；
#     加 time.sleep(1.2) 跨过秒边界后才真正验出缺陷。
#     另一处「先建后验」也修了：新建项目初始统计 0/0/0 与实时统计不同，
#     首次调用属合法「真变化」，测试必须先结算一次再验「重复读不写」。
#
#     本轮附带把 15 个工具脚本逐个做了「跑前/跑后真实数据快照对比」，
#     确认**只有** test_gb_fallback.py 会写真实项目；其余 14 个新增 0 / 变化 0。
#     全量 selftest 的唯一残留副作用是 project_meta 的 updated_at（即缺陷二），
#     已在产品层修掉。
# v0.1.222：修三处「同一件事两个答案」的落盘缺陷
#   ① 重跑整卷无条件覆盖卷内文件 → 用户手填的 B 类表被静默销毁，
#      接口仍返回 ok=True。改为默认保留、显式 overwrite 才重建。
#   ② supervision_integration._proj_root 绕开 pm.PROJECTS_ROOT，
#      从 TEMPLATES_DIR 反推安装目录 → 数据目录可配置失效、测试隔离静默失效
#      （实测：临时项目的卷落进了真实 data/projects）。
#   ③ 验证脚本硬编码真实项目 PID，跑一次就改用户真实产出。
# v0.1.223：补上 0.1.222 的两个「半交付」
#   ① 后端 VolumeReq 有 overwrite，页面却没有任何入口 —— 用户能守住手填内容，
#      但永远没法按新台账重建（只能手动删文件）。补勾选框并真的提交该字段。
#   ② kept 项被无条件记进 generated —— 真实浏览器实测「生成文件 2 个」而卷内
#      一个文件都没写，返回体与磁盘对不上（又是「同一件事两个答案」）。
#      改为 generated 只记 created/replaced，kept 单独记账并在界面/待办清单说明。
# v0.1.224：真机回传暴露的三个问题（WORKbuddy 实测 P68/F0/S2 @ 20261110_070527）
#   ① 每轮只跑 selftest，20 个专项 test_*.py 从来没上过真机 —— 设备台账/整卷/
#      备份恢复这些**功能链路**零覆盖；selftest 里 2 条设备断言还因本机无设备
#      而 skip，「68 全过」听起来全绿、设备链路当轮根本没验。wb_loop 增加
#      run_suites()：每轮跑全部 test_*.py，任一失败本轮即判 failed，明细进
#      suites.json 与 report.md 表格。
#   ② 全新安装（data/ 空）跑自检必出 2 条红：一条「切不回用户原项目」、
#      一条「审计流水被污染」—— 两者都源于把「初始状态」当成了「缺陷」。
#      改为：无项目可切记 SKIP（有项目却切不回仍算 FAIL）；审计文件开跑前
#      不存在时，历史边界按字节 0 处理并按 token 精确清除（实测前=0 后=0 清除 6）。
#   ③ relations._merge_index_devices 只在「从台账新增了设备」的分支写
#      stats["devices"]，空项目/纯图纸项目直接 return → stats.devices 是 None
#      而 devices 列表是 []，同一事实两个答案。改为出口处无条件写实际条数。
# v0.1.225：用马诺诺真实资料（65 个文件 / 62 个唯一内容，工位实测全天）
#           跑出来的 4 个问题（与 v0.1.224 的专项套件改动互不冲突）
#   ① 批次上传**整批末尾才写一次索引**：一次几十个大 DWG/PDF 要跑几分钟，
#      这期间任何别的写入都会被末尾那次「旧快照整份覆盖」。实测同一天里
#      index.json 从 51 条掉到 43 条，parsed_cache 有 57 份解析结果 ——
#      14 个文件在资料库里凭空消失，界面一个字都不报。
#      改为每 5 个文件/5 秒 `scanner.merge_index_entries()` 锁内合并。
#   ② 缓存与索引没有对账机制：丢掉的条目没人补回来。
#      新增 `scanner.reconcile_index()` + `/api/index/reconcile`。
#   ③ .xls（Excel 97-2003）不在支持列表：现场 3 个箱单/斗提机表全被判 skipped，
#      查不到内容。新增 `parse_xls`（xlrd + HTML 表格双分支，国内系统导出的
#      「假 xls」其实是 HTML）。
#   ④ .rar/.zip 压缩包被跳过时提示不明确：用户传了 5MB 图纸包，只看到「跳过」。

# v0.1.226：外部工具只搜 C 盘，把「本机有」误报成「本机没有」
#   现象（2026-11-10 工位实测）：25 张 DWG 全部返回
#     「未找到 ODA File Converter（可设环境变量 ODA_CONVERTER）」，解析文本 0 字；
#     16/30 张扫描件 PDF 无文字层；竣工图清稿阶段超时。
#   老板一句「本机应该有这些条件，你扩大一下检测范围」才发现：
#     ODA      D:\ODA\ODAFileConverter\ODAFileConverter.exe
#     AutoCAD  D:\Program Files\Autodesk\AutoCAD 2020\accoreconsole.exe
#   两个都确实装着，只是**不在 C 盘**。
#   根因：`_find_oda_converter()` 只查 `os.environ["ProgramFiles"]`（恒为 C 盘）
#     加一个写死的 `C:\ODA\...`，全盘只覆盖一个盘符；注册表里的
#     `InstallLocation`、其它盘符的 `\Program Files` 一概没看。
#   后果不是「工具缺一个」，而是**资料库对图纸基本不可用**：
#     60 个真实文件里只有 19 个能抽出正文（32%），其中 DWG 是 0/25。
#   修法：新增 `_find_external_tools()`，一次把三样工具查清并缓存 ——
#     ① 盘符枚举：C..Z 里真实存在的根目录全进搜索面（不再假设只在 C 盘）；
#     ② 注册表：HKLM/HKCU 的 Uninstall\* 读 DisplayName→InstallLocation，
#        覆盖任意安装路径（ODA/Teigha、AutoCAD）；
#     ③ 通配兜底：只在 `<盘>:\ODA*`、`<盘>:\Program Files*\ODA*` 下递归，
#        不做全盘扫描，避免拖慢启动；
#     ④ PATH 兜底：`where`；
#     ⑤ 同时返回 `accoreconsole.exe`（AutoCAD 无界面脚本引擎，ODA 缺位时的
#        DWG→DXF 备份通道）与 `tesseract.exe`（扫描件 OCR）。
#     查过哪些盘写进 `searched_roots`，报错信息带出来，现场不用再猜。
#   验证：把 earlier 报「未找到转换器」的两张真图重跑 ——
#     X398·301 Manono 粗碎车间布置图  parsed  text=1300  6.3s
#     火法部分流程图                 parsed  text=26251 5.9s
#   遗留（下一轮解决，不在本次范围内假装已修）：
#     · `title_block` 仍为 {}，图签栏抽取另有缺陷；
#     · 本机 Tesseract 只有 eng+osd，缺 chi_sim，中文扫描件仍走不通；
#     · accoreconsole 已能定位但还没接进 DWG 转换链路。

# v0.1.227：马诺诺真实资料全阶段跑下来暴露的 8 个问题。
#   共同点：**每一个都会让「看起来修好了」和「实际能不能用」脱钩**，
#   而且没有一个会在界面上明说。
#
#   ① 交付用的解释器 ≠ 自测用的解释器（最根本的一条）
#      循环用 sys.executable 起服务、跑自测，也就是「谁拉起循环就测谁」；
#      老板双击 open_or_start.bat 时优先用 workbench/venv。两套环境装的包
#      可以完全不同 —— 实测本机：venv 有 paddleocr 没 xlrd，宿主内置 python
#      有 xlrd 没 paddleocr。于是「我这边 .xls 通过、OCR 未启用」，
#      老板那边正好相反。自测报告有结论，但验的不是同一个程序。
#      修：wb_loop._runtime_python() 统一 venv 优先；env.json 同时记录
#      loop 与 runtime 两个解释器及各自包版本，差异不再靠猜。
#
#   ② requirements.txt 漏了 xlrd
#      v0.1.225 新增 parse_xls 依赖 xlrd，但没写进依赖清单。venv 里确实没有，
#      真机上传 .xls → ImportError → parse_file 记成「skipped/缺少依赖」，
#      用户传了文件、库里一条内容都没有。而自测解释器恰好有 xlrd，
#      所以自测永远是绿的。修：补 xlrd>=2.0.1，装进 venv。
#
#   ③ 自测环境里带着宿主沙箱，测的是沙箱不是产品
#      WorkBuddy 这类宿主会往 PYTHONPATH 塞 sitecustomize，改写删除行为：
#      单轮批量删除超 50 个文件就 SystemExit(1)。实测删一个 59 文件的测试项目
#      → 工作台主进程当场退出 → 整轮级联失败，报告上像「十几个功能同时坏了」；
#      另有两个原子写套件因 %TEMP% 被拦成 PermissionError [WinError 5] 报红，
#      产品代码一行没错。修：wb_loop._child_env() 把 shim 目录从子进程
#      PYTHONPATH 里滤掉（只影响为测试创建的进程；目标用户机器本就没有这层）。
#
#   ④ 删项目能把整个服务带走
#      delete_project 里一句裸 shutil.rmtree：
#        · 目录被 chroma.sqlite3 / upload_queue 占着 → PermissionError，
#          异常冒到 FastAPI 变 500，而目录已删一半，项目成残骸；
#        · SystemExit/KeyboardInterrupt 不是 Exception 子类，拦不住，
#          直接从请求处理函数逃出去 → uvicorn 主进程结束。
#      修：新增 _safe_rmtree()（重试 + 收集 BaseException + 报残留），
#      失败时返回 ok=False 并记审计，绝不假装删成功。
#
#   ⑤ 解析器修好了，老资料不会重新解析（"修了跟没修一样"）
#      判重条件只有 status=="parsed"。ODA 探测修好、DWG 已能从 0 字抽到
#      1300/26251 字，但 25 张 DWG 的缓存里仍是
#      {"status":"partial","text":"","error":"未找到 ODA File Converter…"}，
#      扫描一律跳过。用户不知道该重传哪些，等于这次修复对存量数据完全无效。
#      修：新增 config.PARSER_VERSION + 索引/缓存双写版本戳，判重改为
#      「parsed 且是当前版本解析的」；新增 scanner.reparse_stale() 与
#      POST /api/index/reparse 把差距量化出来；上传去重同样按版本判。
#
#   ⑥ selftest.py 自己会崩，把崩溃伪装成 6 个功能缺陷
#      phase1 里 details 只在 if items: 内赋值，后面却在外面读 →
#      UnboundLocalError。条目数为 0 时整段崩掉，phase3 全部「无设备数据」。
#      修：details/detail_fail 提前初始化。
#
#   ⑦ 扫描等待写死 240 秒，真实资料永远等不到
#      63 个文件含 25 张 DWG（每张 ODA 转换 6 秒）+ 16 份扫描件 OCR，
#      实测 8~20 分钟。固定 240 秒 → 「扫描完成 {}」「条目 0」→ 下游全红。
#      修：改为按进度等待（最多 30 分钟，done 连续 90 秒不动才判卡死）；
#      并新增「扫描统计可读」断言区分「没扫完」与「扫完但没 stats」。
#
#   ⑧ 单实例锁在 UTF-8 模式下会误判（机制成立，双开未实测到）
#      用 tasklist 输出找 pid 判断存活。中文 Windows 的 tasklist 是 GBK，
#      而 text=True 不指定编码时按默认编码解码；进程开了 UTF-8 模式
#      （PYTHONUTF8=1 / -X utf8）就是 UTF-8 → reader 线程抛
#      UnicodeDecodeError。这个异常在子线程里，**不冒泡**，于是 stdout 为空、
#      「pid 已不在」→ 锁被当成过期 → 覆盖锁继续启动。
#      实测证据：2026-11-10 09:29 与 09:37 两轮日志开头都留下
#        "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd0"
#      这一行；也就是说判活确实走空了。只要此时真有一个循环在跑，
#      就会变成两个循环写同一个仓库。
#      ⚠ 更正：我最初看到「两个 wb_loop + 两个 start.py」就断定已经双开，
#      这是错的 —— venv\Scripts\python.exe 是个 241KB 的启动器，
#      它会再拉起真正的解释器，所以「启动器 + 真身」天然成对出现。
#      机制成立，后果未实测到，按潜在缺陷修正，不夸大成已发生的事故。
#      修：_pid_alive() 改用 Win32 OpenProcess（零解析、零编码），
#      判不出来时按「活着」处理（宁可拒绝启动，也不要双开写仓库）。
#
#   附带：
#   · DWG 图签栏恒为 {}：抽取区域假定"图框右下 45%"，而模型空间并排多图/
#     包围盒被拉远时那片区域是空的。改为区域没匹配到就全图再找一遍，
#     并标注 _source。实测两张真实图纸由「空」变为可抽出图号/图名。
#   · OCR 全线不可用：本机 PaddleOCR 3.7.0 + paddlepaddle 3.3.1 的 predict
#     必崩（oneDNN: ConvertPirAttribute2RuntimeAttribute not support），
#     FLAGS_use_mkldnn=0 / FLAGS_enable_pir_api=0|1 三组组合全部无效；
#     另外先 import paddle 再 import torch 会 WinError 127（shm.dll）。
#     改为 Tesseract 优先：随程序带 chi_sim（workbench/ocrdata，2.4MB，
#     免管理员、现场离线可用），首次使用时把系统 eng/osd 复制进来；
#     _get_ocr() 里改成先 import torch 再 import paddleocr。
#     识别质量对工程图纸一般（噪声多），但「有字可搜」远好过「0 字」。

# 【v0.1.228】自测循环每轮收尾后工作区必定是脏的 —— 根因是「先提交、后补写」。
#
#   现象：reports/<ts>/report.json 与 reports/.wb_loop_state.json 在远端提交里
#         是旧内容，本地却是新内容；每轮结束 `git status` 都有 2~3 个文件被改。
#   根因：wb_loop.finish() 先落盘再 commit（这一步是对的），但 push 完成后又把
#         回传结果（pushed / git add|commit|push 的 rc）补写回 report.json；
#         记账函数 record_state 也在 commit 之后写 .wb_loop_state.json。两个文件
#         都是**跟踪文件**，于是「提交 → 又改 → 不再提交」，脏状态每轮必现。
#   后果：下一轮 PULL 段看到脏工作区就 `git stash -u`，而 stash 会把刚 makedirs
#         出来的**空报告目录**一并收走 → 那一轮报告目录凭空消失。外部包装脚本
#         D:\fangong-auto\auto_round.py 当初就是为了绕开这个缺陷才写的。
#   修法：① push 结果改记 reports/<ts>/transport.json，状态文件挪出跟踪范围，
#         两者都进 .gitignore；② 收尾多加一道 _assert_clean_after_push()，
#         脏了就留证据到 reports/_dirty_after_push.txt，不再无声无息。
#   验证：一轮跑完后 `git status --porcelain -uno` 必须为空；auto_round.py 可以退休。

# 【v0.1.229】扫描「跑完了、0 个文件」，而盘上明明有 65 个 —— 三个缺陷叠在一起。
#
#   现象：20261110_105123 轮 阶段1 报「扫描完成: {}」「资料库条目数 0」
#         「识别车间 []」，下游连带 6 条「无设备数据」。接口全部 200，看不出错。
#   根因①自测的卡死判据选错了：v0.1.227 定的规则是「done 连续 90 秒不动就放弃」。
#         但 63 个真文件里 25 张 DWG 每张要 ODA 转换约 6 秒、十几份扫描件 PDF 走
#         Tesseract OCR，**单个文件就能上百秒**，done 是「处理完一个才 +1」，
#         中途当然一动不动。实测 93.6 秒就放弃 → 扫描被自己打断。
#   根因②/api/scan/status 不返心跳：SCAN_STATUS 里维护着 heartbeat，却没暴露，
#         调用方除了「done 变没变」没有别的判活依据，只能猜。
#   根因③扫描线程吞异常：_scan_with_stats 里是裸的 background_scan 调用，
#         线程里抛任何东西都直接消失，running 停在 true / stats 是 None，
#         界面上看起来就是「扫描跑完了，0 个文件」。
#   修法：① 状态接口补 heartbeat 与 error；② 扫描线程 except BaseException
#         把异常写进 status["error"]（宿主 sitecustomize 抛的是 SystemExit，
#         用 except Exception 拦不住）；③ 自测改看心跳，阈值 300 秒，
#         并把「测试没等到」单独记一条，不再和「程序出错」混在一句里。
#   验证：同一批 63 个真文件手工重扫 found=63 parsed=63 vectorized=63 failed=0。

APP_VERSION = "0.1.230"

# 解析能力版本号（与 APP_VERSION 独立：界面/接口小改动不必重解析全库）。
# **只要改了「同一份文件能抽出多少内容」，就把这个号加一** ——
# scanner 用它判断索引里的旧结果是否还能复用，加了号升级后第一次扫描
# 会自动重解析旧文件，用户不需要重新上传。
# 取值用日期+序号，读起来就知道是哪天改的。
#   2026-11-10.1  ODA/AutoCAD/Tesseract 跨盘符发现；.xls 双分支；
#                 PDF 图形件 OCR 兜底；failed 不再被改写成 partial
#   2026-11-10.2  图签栏全图兜底；Tesseract 中文 OCR 接管；
#                 _get_ocr() 先 torch 后 paddleocr
#   ⚠ 只要解析结果会变，就必须加号。有一轮我在改动中途跑自测，
#     服务内存里还是旧解析器、却把 "2026-11-10.1" 写进了缓存 ——
#     版本戳说"是最新的"，内容其实是旧的，比没有版本戳更误导。
PARSER_VERSION = "2026-11-10.2"


# v0.1.230：自测自身的三个缺陷，其中一个是**会删用户数据**的
#     ① 最严重：自测收尾「还原当前项目」把 228 台设备的真实项目换成了空壳
#        现象：真机 20261110_083316 之后，用户打开程序看到的是「v01201实测_012805」
#        （0 文件 / 0 设备），他原来的项目 322fef90（1 文件 / 228 台设备 / 6 卷归档）不见了。
#        数据没删，但**当前项目指针被换走了**，观感就是「我的资料没了」。
#        根因：跑自测前先把当前项目切到自测项目，收尾时用「名字前缀像测试」
#        （自测/实测/v01201实测_…）判断原项目是不是残留 —— 而用户真实项目
#        恰好叫「实测_20261103_132055」，被自己的名字判成残留；反过来
#        「v01201实测_012805」前缀不匹配、被当成真实项目留下来。
#        **名字是记录，不是判据**：判据应是「有没有内容」（file_count/device_count），
#        名字只用来生成说明文字。
#        改法：抽出 pick_restore_target(items, origin_pid) —— 先看内容、再看名字；
#        有内容就保留（哪怕名字像测试，并显式说明「认定为真实项目」）；
#        无内容才按 content 挑一个有内容的接任者，挑不到就明确说「保持不动」
#        而不是硬切回一个空壳。7 处切换统一走 switch_for_selftest() 包装。
#        回归：tools/test_restore_target.py 9 条断言 / 5 场景，含反向验证
#        （把判据改回「只看名字」，场景1/2 必须判错）。改前 2 FAIL，改后 9 PASS。
#     ② 「把慢当成坏」：整卷接口在真实资料上要 85 秒，自测 TIMEOUT=60 →
#        code=-1，被记为「无产出且无待办 → 静默空转」当成功能失败。
#        实测（沙箱，项目 322fef90 / 19 车间 / 228 台设备）单次 85.4 秒；
#        这是**正常耗时**（整册逐图逐表生成 docx），不是卡死。
#        改法：整卷单独用 _VOLUME_TIMEOUT=240；超时文案改成
#        「超时未返回（240s），本轮未判定功能对错」，与真正的「静默空转」分开。
#     ③ 「哪块红了就把哪块不测」：真机 run 083316 的 phase6 只红 1 条
#        （跑完自测用户审计流水未被污染，前=22 后=0），之后 --phases 就变成
#        1,2,3,5，整块 phase6 被拿掉 —— 22 条本来通过的跨接口比对（版本号全来源、
#        待上传数、已入库文件数、设备数、车间清单、项目数…）一并消失，
#        后面几轮「PASS」其实没覆盖它们。
#        根因查到了：_audit_log_path() 在 /api/status 不可达时**静默回落到**
#        ./data/operation_log.jsonl（沙箱实测 exists=False），于是「前=22 后=0」。
#        改法：审计行清理改为**精确文本匹配**——只删本次自测真写进去的那几行
#        （建/切/删项目、按项目名与 id 精确匹配），项目切换行用
#        PURGE_SWITCH_ROWS 逐条登记；并去掉「没有 tokens 就整段跳过清理」的
#        提前返回（单跑 --phase 6 时不建测试项目，那样清理等于没做）。
#        代价：绝不能用「删掉所有『切换项目』行」这种写法 —— 那会连用户
#        在自测期间自己切的真实操作一起删掉，审计完整性正是审计的全部意义。
#     最终门禁（沙箱全量）：81 条结果 / 78 PASS / 1 FAIL / 8 SKIP，
#     phase6 回到 23 条断言且 23 PASS；审计 345 → 345（用户流水未被污染）。
#     唯一红的一条是 WORKbuddy v0.1.229 自己加的「车间名合法」探针，
#     它照实报出 10/20 可疑车间名（中矿堆/总图/水源取水/粉矿堆…），
#     那是真实业务问题、且 WORKbuddy 已把处理策略交回给我们定，
#     不是自测要替他改的产品行为，因此本轮不动它。
# v0.1.229 —— 见 WORKbuddy 真机实测回归记录
# v0.1.218 —— 备份范围：项目「有什么」和「备了什么」是两套口径
#     现象：备份/恢复与删除前自动备份，都按 project_backup.BACKUP_ITEMS 这份
#     **9 项白名单**打包。而一个真实项目的数据目录里有 19 类业务数据。
#     实测（本轮，data/projects 11 个真实项目）白名单漏掉的：
#       generated_docs        10 个项目共 178 份 docx（6.45 MB）← 最严重
#       doc_relations.json    10 个项目      construction_logs.json 9 个
#       volumes/              1 个项目 11 个文件
#       workshop_assign / equipment_merge / supervision_registry /
#       file_level / upload_log.jsonl / .node_id / upload_queue/ 各 1~11 个
#     后果不是「少打包一个文件」，而是**删除或恢复项目会静默丢数据**：
#       · delete_project(backup=True) → backup_before_delete() → export_project()，
#         走的是同一份白名单，所以「删除前已自动备份」这句提示给的安全感是假的；
#       · import_project() 按 zip 内实际条目解压，包里没有的永远恢复不出来。
#     实测证据（临时 DATA_DIR）：
#       · 造种子项目 → 导出 → 包内 generated_docs 条目 = 0，
#         而 exports/uploads 完好 —— 两条路径都返回 ok:true；
#       · 拿真实项目 322fef90（102 个文件 / 36 份 docx / 11 份归档卷）复制到
#         临时 DATA_DIR 做导出→导入：改前 generated_docs 恢复 0 份，
#         改后 102 个文件全部逐字节一致、36 份 docx 一份不少；
#       · 直接走 delete_project(backup=True, delete_data=True)：改前最新备份里
#         generated_docs 条目 0 个，改后 14/14（种子项目 0b15f685 的 14 份）。
#     改法：**以目录实际内容为准，不靠白名单**。
#       ① 打包遍历项目目录下每一个条目（文件 + 空目录，如 vector_db 尚未建索引时）；
#          只跳过运行期垃圾（__pycache__ / *.pyc / *.tmp / *.swp / *.lock），
#          以后新增一类数据目录不必再回来改清单。
#       ② 覆盖导入原来按同一份白名单「清空」，改为**只清空备份包里确实带了的
#          顶层条目**：包里有就整体替换，包里没有就原样留着 —— 新备份是干净替换，
#          旧备份（不含 generated_docs）也不会借「恢复」之名删数据。
#       ③ BACKUP_ITEMS 降级为兼容常量，不再参与打包/清空判定。
#     回归：tools/test_project_backup_complete.py 18 条断言（B1 逐类覆盖、
#     B2 成果进包、B3b/c/d/e 恢复后逐字节一致、B4b 覆盖导入不误删、B5 未知新目录）；
#     改前 5 PASS / 13 FAIL，改后 18 PASS / 0 FAIL；把导出改回白名单写法
#     立回 5/13（rc=1），确认测试真能抓住。
# v0.1.217 —— 审计流水自身的两处「同一件事两个答案」
#     ① 时间格式分裂（本轮实测发现，是 v0.1.216 自己引入的回归）：
#        v0.1.216 把写盘逻辑从 app/main.py 抽到 app/op_log.py 时，顺手把
#        `time` 从 datetime_now() 的 "20261029_2141" 换成了
#        "%Y-%m-%d %H:%M:%S"。历史 325 条全是老格式，新写的全是新格式，
#        同一份 operation_log.jsonl 混着两种时间。前端列表与 CSV 导出的
#        「时间」列是原样透传，两种格式既不能排序也不能按日期筛选；
#        而两条写入路径各自都成功，界面上根本看不出异常。
#        修法：op_log._log_time() 固定回 "%Y%m%d_%H%M"，与历史一致；
#        要换格式必须连带迁移历史数据 + 同步改前端解析，不能只改新写入一侧。
#     ② 上传审计「先记账、后执行」（v0.1.6x 起就存在，本轮核对时发现）：
#        /api/upload-files 在函数第一行就 _log_op("upload", f"上传 {n} 个文件")。
#        文件全部超限/为空/是 CAD 临时锁文件、或中途抛异常时，一个都没落盘，
#        审计却说「上传了 N 个」。与 v0.1.216 修好的 create「先记账后执行」
#        是同一类错误。修法：循环结束后按 results 的真实 status 统计
#        （parsed/partial/duplicate 计入），为 0 就不写。
#     ③ 自测污染真实审计流水（上一轮实测 325 → 346）：
#        selftest 真建/真切/真删项目，会真写用户的审计流水。用户事后查
#        「项目怎么没了」，流水里混着 21 行测试记录 —— 流水还在但不可信了。
#        （这与 v0.1.216 刚修的「审计空白被当成否定证据」是同一件事的两面：
#        缺记录会被误读，假记录会让真记录一起失去可信度。）
#        修法：run() 开跑前记「行数 + 字节长度 + 末行」快照；finally 里以
#        字节长度为历史边界，只删边界**之后**追加且含本次自测独有标识
#        （项目名/项目 id）的行，历史行一个字节都不动；最后断言
#        「行数与末行回到开跑前」。阶段⑥ 因此升到 15 条断言。
#     反向验证：把 op_log 的时间格式改回 dash → 单测 J1 FAIL；
#     把上传审计挪回函数开头 → 上传单测 FAIL；把清理函数改成空实现 →
#     阶段⑥ 新断言 FAIL（前=325 后>325）。
# v0.1.215：修「删掉当前项目后指针悬空」——用户删掉自己的工程，下次打开看到
#   「当前未选择项目，请先新建或选择项目」，观感是「我的资料丢了」。
#   根因：project_manager.delete_project() 对当前项目只做 os.remove(
#   CURRENT_PROJECT_FILE)，指针直接消失，没有任何接任逻辑。现场已反馈过一次
#   （「打开程序发现自己的工程不见了」），当时只当成测试污染处理，没修产品行为。
#   改法：① 删当前项目前先挑接任者（优先 file_count/device_count>0 的项目，
#   其次任意项目，一个都没有才允许置空），资料处理完再切指针；② 新增
#   ensure_current_project()，启动时对「指针缺失 / 指向已删项目」的机器自愈，
#   让已经踩过这个坑的安装也能恢复（否则装上新包照样看不到工程）；
#   ③ 删除结果里加 switched_to 并写进 message，前端 alert 能直接告诉用户
#   切到了哪个项目，而不是只弹一句「已删除」。
#   附带修好自测：阶段⑥ 的 _ORIGIN_PID 会因指针为空而成为空串，该断言只能落
#   `目标=?` FAIL（58/1）；现在指针不会悬空，它也稳定可核验。新增 6.12
#   「有项目时当前项目指针不悬空」，以及 tools/test_delete_project_pointer.py
#   32 条断言（含 H 组启动自愈）。
# v0.1.214：修「测试把车间归属写进用户真实项目」——与 v0.1.213 的队列污染同源。
#   现象：用户真实项目 322fef90 的 workshop_assign.json 里 22~28 条记录，
#   其中 21~27 条 file_path 指向 /tmp/fgpath_*（全是单测样本）；
#   界面「待人工确认」从 0 涨到 10，用户看到一堆自己没上传过的文件。
#   根因：workshop_assign._assign_file() 只认「当前项目」，不看调用方给的 data_dir；
#   scanner.reparse_file(path, data_dir=...) 里调 assign_workshop(...) 不带目录，
#   于是解析缓存/index/队列都落临时目录、**车间归属却落用户真实项目**。
#   改法与 upload_queue 完全一致：模块级 _ISOLATED_DIR 放在 _assign_file 这一层，
#   任何内部调用都必须尊重它。顺带补了 C7/C8/C9 三条断言，其中 C8 初版只比
#   「键集合差异」，样本 sha 恒定导致恒 PASS —— 已改为按内容全等比较。
# v0.1.213：修「测试往用户真实队列写垃圾包」——同一件事两个落点的又一处。
#   现象：跑完单测/自测后，用户项目的待上传队列里出现「设备台账.xlsx」「q.xlsx」
#   这类根本没上传过的条目（实测 322fef90 pending 由 0 变 4）。
#   根因是 upload_queue._ensure() 只看「当前项目」，不看调用方给的 data_dir；
#   而 scanner.reparse_file(path, data_dir=...) 会调 upload_queue.enqueue(res)，
#   于是解析缓存/index 落进临时目录、**队列包却落进用户真实项目**。
#   第一版修法（进 enqueue 时临时改 QUEUE_DIR、finally 还原）还不够：
#   _enqueue_locked 中间调 _node_id()，_node_id() 内部又 _ensure() 一次，
#   不带参数就把 QUEUE_DIR 重置回当前项目 —— 结果索引进了临时目录、包进了真实队列，
#   同一份入队逻辑两个落点算出两个目录。
#   改法：模块级 _ISOLATED_DIR 覆盖，放在 _ensure 这一层，任何内部调用都得尊重它。
# v0.1.212：修「同一件事两个答案」的车间版本 ——
#   /api/workshops 报 19 个车间，同一时刻 /api/relations.workshops 是空数组 []，
#   而 228 台台账设备自己身上明明带 19 个车间名。根因在 relations._merge_index_devices()：
#   它只补 devices 与 stats，从不重建 graph["workshops"]，而 build_relations() 是唯一
#   会建 workshops 的地方 —— 只导入台账、没跑图纸关联时图谱是 _blank_graph()，
#   workshops 恒为 []。用户直接撞上的后果：19 个真实车间的详情接口
#   GET /api/relations/workshop/<车间> 全部 404（我逐个实测过）。
#   阶段⑥ 原来只断言「设备里能解析出 >=1 个车间」，这条照样 PASS，
#   所以缺陷一直漏过去 —— 现在改成 relations.workshops 与 api.workshops 成对比对。
# v0.1.211：修「同一件事两个答案」的第三个来源 —— /api/mobile/config 里的 version
#   原来写死 "version": "0.1.99"（v0.1.99 新增该路由时填的字面量，之后 111 个版本没跟着改）。
#   实测 2026-11-07 13:1x（工作树 0.1.210）同一时刻三处：
#     /api/status.version        = 0.1.210
#     /api/update/check.current  = 0.1.210
#     /api/mobile/config.version = 0.1.99   ← 错
#   移动端拿它判断「是否需要更新」，于是永远认为自己 0.1.99、永远提示有更新。
#   为什么前几轮一直没抓到：阶段⑥ 原来只比 status 与 update/check **两点**，
#   那条断言照样 PASS。这次做的是「把 /api/status 每个字段挨个找它的权威来源
#   成对比较」的全量盘点，才挖出这个藏在移动端配置接口里的第三处。
#   现在阶段⑥ 改成「列出全部版本号来源再逐一比对」，以后新增接口报版本
#   加进列表即被自动校验。反向验证：把 mobile 这处改回 0.1.99 → 阶段⑥ 报
#   「版本号全部来源一致」FAIL、exit=1。

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
