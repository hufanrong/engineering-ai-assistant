# 繁工AI 本地解析工作台 - 配置
# 修改后重启服务生效。所有路径建议使用英文，避免编码问题。

import os

# ============ 基本 ============
HOST = "127.0.0.1"          # 只在本机访问；如需局域网访问改为 0.0.0.0
PORT = 8756                 # 端口，冲突可改
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

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
EQUIPMENT_TAG_RE = r"(?<![A-Za-z0-9])([A-Z]{1,3}-\d{1,6}(?:[/-][A-Z]{0,3}\d{0,4})?)(?![A-Za-z0-9])"

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
PLATFORM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "platform_data")
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
