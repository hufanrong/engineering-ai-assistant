# 繁工AI · 本地解析工作台（MVP v0.1.3）

> 复杂工程，AI 化简 —— 在你自己电脑上运行的文件深度解析引擎。
> 配套开发提示词文档：`工程AI助手_开发提示词_v3.md`（v3.6 本地解析工作台 / v3.7 方案智能生成）。

## 它做什么

把电脑里的工程资料文件夹（图纸、台账、清单、方案、计划、照片…）变成**可被 AI/Agent 读取的结构化解析库**：

```
选择文件夹 → 递归扫描 → 深度解析 → 结构化入库 → 分块向量化 → 打包待上传（云端合并）
```

| 能力 | 说明 | 状态 |
|---|---|---|
| PDF / Word / Excel / 文本解析 | 提取全文 + 表格结构化（台账表头/行）| ✅ 默认启用 |
| 实体浅提取 | 自动识别设备位号（如 P-101）| ✅ 默认启用 |
| 向量化存储 | 分块(500+50) + 中文 embedding + Chroma 本地库 | ✅ 默认启用（首次下载模型约 470MB） |
| 上传队列 | 解析结果打包待命，SHA256 去重，配置云端后一键上传 | ✅ 默认启用 |
| AI 检索 | 网页内可直接检索解析库，验证 Agent 可读 | ✅ 默认启用 |
| 图片 OCR | 扫描件/现场照片文字识别 | ⚪ 可选（装 PaddleOCR） |
| CAD 图纸 | DXF 解析文本/块；DWG 需 ODA 转换 | ⚪ 可选（装 ezdxf + ODA） |
| Project 计划 | 任务/工期/前置关系结构化 | ⚪ 支持 XML 格式（.mpp 需先另存为 XML） |

## 系统要求

- Windows 10/11 64 位（本版本）
- Python 3.10+（安装时**勾选 "Add Python to PATH"**）→ https://www.python.org/downloads/
- 磁盘：程序约 300MB + 模型约 470MB + 你的资料空间
- 首次安装需联网（下载依赖与 embedding 模型）；之后可离线使用

## 部署步骤（5 分钟）

1. **解压**：把 `fangong-workbench` 文件夹放到 `D:\fangong-workbench`（路径建议全英文，避免个别依赖中文路径问题）
2. **安装依赖**：双击 `install.bat`（首次约 1-3 分钟，会自动创建 venv 并安装）
3. **启动**：双击 `run_workbench.bat`，浏览器自动打开 `http://127.0.0.1:8756`
4. **开始解析**：在"① 扫描解析"输入你的资料文件夹路径（如 `D:\工程资料\XX项目\施工图纸`），点"扫描解析"，后台自动处理全部支持的文件
5. **验证**：切到"③ AI 检索"，输入如"1号车间 离心泵 P-101"，能看到解析库命中内容即成功

## 启用可选能力

| 能力 | 操作 |
|---|---|
| 图片 OCR | 打开命令行：`pip install -r requirements-ocr.txt`（约 1.5GB），再把 `app/config.py` 中 `PARSE_IMAGE` 改为 `True` |
| CAD 解析 | `pip install ezdxf`；DWG 另装免费 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)，安装到默认路径，再把 `PARSE_CAD` 改为 `True` |
| Project 计划 | 无需安装；用 MS Project 把 `.mpp` **另存为 XML** 再放入文件夹即可被解析（直接放 .mpp 暂不支持，避免 Java 依赖） |

> 未启用/未装依赖的类型会被标记 `skipped`，**不影响其他文件解析**。

## 上传云端合并（多台电脑）

1. 每台电脑在 `app/config.py` 里设置 `NODE_NAME`（如"办公室电脑A"、"工地笔记本B"）
2. 配置 `CLOUD_ENDPOINT`（云端主库服务地址，部署后发放）和 `CLOUD_API_KEY`
3. 各电脑本地解析完成后，在"④ 上传队列"点"上传到云端"；云端按 SHA256 自动去重、以设计院编号为准归并冲突
4. 未配置云端时，解析结果**安全保留在本机** `data/upload_queue/`，随时可上传

## 目录结构

```
fangong-workbench/
├── start.py                # 启动入口（自动开浏览器）
├── install.bat             # 一键安装（venv + 依赖）
├── run_workbench.bat       # 一键启动
├── requirements.txt        # 核心依赖
├── requirements-ocr.txt    # 可选：OCR 依赖
├── app/
│   ├── config.py           # ★ 配置（解析开关/节点名/云端地址）
│   ├── main.py             # FastAPI 服务与 API
│   ├── scanner.py          # 文件夹扫描 + 解析 + 入库 + 队列
│   ├── vector_store.py     # 分块/向量化/检索
│   └── upload_queue.py     # 云端上传队列
├── parsers/engines.py      # ★ 深度解析引擎（PDF/Word/Excel/OCR/CAD/Project）
├── web/                    # 网页界面（index.html + app.js）
└── data/                   # 运行时数据（自动生成，可整体备份/迁移）
    ├── index.json          # 已处理文件登记（幂等去重）
    ├── parsed_cache/       # 解析结果缓存（详情页读取）
    ├── upload_queue/       # 待上传包（云端合并用）
    ├── vectordb/           # Chroma 向量库
    └── upload_log.jsonl    # 上传留痕
```

## 常见问题

| 问题 | 解决 |
|---|---|
| 端口被占用 | 改 `app/config.py` 的 `PORT` 后重启 |
| 中文路径报错 | 优先放英文路径；或确认 Windows 区域设置支持 UTF-8 |
| 首次检索很慢 | 正在加载 embedding 模型，等一次即可 |
| 大量文件解析慢 | 正常；扫描是后台线程，可继续用电脑。停止请点"停止" |
| 想重扫某文件夹 | 用"强制重扫"（会覆盖旧登记，按最新版本入库） |
| 模型下载失败 | 检查网络；或科学设置后重跑 install.bat 里 pip 步骤 |

## 版本记录

- **v0.1.3**：PDF 表格提取（pdfplumber，含无边框表格文本策略兜底）；手动上传文件接口 `/api/upload-files`（浏览器/手机端直传，记录上传人，落盘→解析→向量化→队列一步完成）；前端上传区
- **v0.1.2**：Project 计划解析实测通过；Excel 同名列自动去重；上传/打包留痕记录查看
- **v0.1.1**：多文件夹批量扫描（每行一个路径）；失败文件人工重试；CAD 文本坐标记录（空间库打底）
- **v0.1.0（MVP）**：主链路（扫描→解析→向量化→队列→检索）打通；PDF/Word/Excel/Text 解析；实体位号提取；可选 OCR/CAD/Project；云端合并队列。

---
© 2026 胡繁荣 · 繁工AI（FanGong AI）· 工程蓝 #1E5AA8 / 安全橙 #FF7A00
