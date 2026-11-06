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
APP_VERSION = "0.1.209"

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
