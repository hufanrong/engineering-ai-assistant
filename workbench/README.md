# 繁工AI · 本地解析工作台（MVP v0.1.95）

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
| 图片 OCR | 扫描件/现场照片文字识别 | ⚪ 可选（装 PaddleOCR，install-full.bat 一键装） |
| CAD 图纸深度解析 | 图框/标题栏（图号图名比例）/设备块坐标与属性/尺寸标注/图层 | ⚪ 可选（装 ezdxf，DWG 需 ODA 转换） |
| Project 计划 | 任务/工期/前置关系结构化 | ⚪ 支持 XML 格式（.mpp 需先另存为 XML） |

## 系统要求

- Windows 10/11 64 位（本版本）
- Python 3.10+（安装时**勾选 "Add Python to PATH"**）→ https://www.python.org/downloads/
- 磁盘：程序约 300MB + 模型约 470MB + 你的资料空间
- 首次安装需联网（下载依赖与 embedding 模型）；之后可离线使用

## 部署步骤（5 分钟）

1. **解压**：把 `fangong-workbench` 文件夹放到 `D:\fangong-workbench`（路径建议全英文，避免个别依赖中文路径问题）
2. **安装依赖**（二选一）：
   - 基础版：双击 `install.bat`（核心解析，约 1-3 分钟）
   - **全套版：双击 `install-full.bat`（核心 + 图片OCR + CAD，约 5-10 分钟，装完自动启用全部解析能力，无需改配置）**
3. **启动**：双击 `run_workbench.bat`，浏览器自动打开 `http://127.0.0.1:8756`
4. **开始解析**：在"① 扫描解析"输入你的资料文件夹路径（如 `D:\工程资料\XX项目\施工图纸`），点"扫描解析"，后台自动处理全部支持的文件
5. **验证**：切到"③ AI 检索"，输入如"1号车间 离心泵 P-101"，能看到解析库命中内容即成功

> 可选依赖自动探测：OCR/CAD 依赖一旦装好，程序下次启动自动启用对应解析，无需改 config。想强制关闭某能力，把 `app/config.py` 的 `AUTO_DETECT_OPTIONAL` 设为 `False`。

## 启用可选能力

| 能力 | 操作 |
|---|---|
| 图片 OCR | 推荐直接双击 `install-full.bat` 全套安装；或命令行 `pip install -r requirements-ocr.txt`（约 1.5GB）。装好后自动启用 |
| CAD 图纸 | 全套安装已含 ezdxf（DXF 直接解析）；DWG 另装免费 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)，安装到默认路径即可自动转换 |
| Project 计划 | 无需安装；用 MS Project 把 `.mpp` **另存为 XML** 再放入文件夹即可被解析（直接放 .mpp 暂不支持，避免 Java 依赖） |

### CAD 深度解析内容（v0.1.4）

每张图纸解析出**空间结构**（为后续"3D 效果数据库"打底）：

| 提取项 | 说明 |
|---|---|
| 图框边界 | 图纸范围坐标，识别整图布局 |
| 标题栏字段 | 图号 / 图名 / 比例 / 设计 / 制图 / 审核 / 日期 / 版本等 |
| 设备块 | 图块名称 + 插入坐标 + 属性（如位号 P-101、名称 离心泵）+ 缩放 |
| 尺寸标注 | 测量值 + 标注位置（设备间距/设备尺寸） |
| 图层统计 | 各图层实体数量（设备层/标注层/图框层） |

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

- **v0.1.95**：**矿山设备AI助手与资料库深度联动**（新增app/mining_ai_knowledge_link.py；search_equipment_in_knowledge_base在资料库中检索设备信息支持按位号/名称/车间检索返回设备信息/相关文档/相关规范；generate_ai_context_from_knowledge_base从资料库生成AI问答上下文含设备信息/相关文档/规范标准/吊装参数构建专业系统提示词和用户提示词；multi_knowledge_base_search多库联合检索项目库+平台规范库+设备知识库；get_knowledge_base_stats获取资料库统计信息项目文档数/设备数/车间数/规范数/设备类型数；新增/api/mining-ai-kb/{search-equipment,generate-context,multi-search,stats}端点；前端新增AI知识库联动区）
- **v0.1.94**：**矿山设备资料生成Word文档导出**（新增app/mining_doc_word_export.py；支持8种现场记录类型Word导出施工日志/开箱检验/隐蔽验收/设备安装/试运转/安全检查/吊装作业/焊接记录；export_record_to_word生成标准Word文档含标题/设备信息/数据表格/设备专用要点/签字栏；表格两列布局项目+内容；字体设置宋体正文/黑体标题；batch_export_to_word批量导出；自动关联设备专用要点；新增/api/mining-word/{export,batch-export}端点；前端新增Word导出区）
- **v0.1.93**：**矿山设备资料生成与现场记录联动**（新增app/mining_doc_record_link.py；8种现场记录到工程资料映射施工日志/开箱检验/隐蔽验收/设备安装/试运转/安全检查/吊装作业/焊接记录各含字段映射13-24项；generate_doc_from_record根据现场记录自动生成工程资料文档自动填充字段标记已填/待填计算完成率；_generate_doc_content生成标准文档格式含编制审核批准签字栏；batch_generate_docs_from_records批量生成；check_record_completeness_for_doc检查现场记录完整性判断是否足够生成资料必填项完成60%以上可生成；自动关联设备专用要点；新增/api/mining-doc-record/{mapping,generate,batch-generate,check-completeness}端点；前端新增资料记录联动区）
- **v0.1.92**：**矿山设备知识库持续完善（增加更多设备类型）**（mining_equipment.py设备类型从205种扩充至458种；矿山设备84种新增凿岩台车/掘进台车/锚杆台车/装药台车/扒渣机/梭式矿车/罐笼/箕斗/主通风机/空气压缩机/主排水泵/矿用变压器/除尘风机/注浆泵/喷浆机/瓦斯抽放泵等；选矿厂设备95种新增对辊破碎机/立式冲击破碎机/高压辊磨机/圆筒筛/脱水筛/除铁器/金属探测器/砂泵/旋流器组/斜板浓密机/转鼓过滤机/立盘过滤机/加压过滤机/气流干燥机/高效搅拌槽/计量泵/浓度计/密度计/流量计/pH计/ORP计/品位在线分析仪/X射线荧光分析仪/激光粒度仪等；湿法冶炼设备114种新增高压浸出釜/常压浸出槽/氧压浸出釜/酸浸槽/碱浸槽/氨浸槽/氰化浸出槽/炭浆槽/锌粉置换槽/离心萃取机/脉冲萃取柱/电沉积槽/离子交换树脂塔/石灰乳制备系统/酸雾净化塔/钛泵/氟塑料合金泵/石墨换热器/降膜蒸发器/DTB结晶器/卧式刮刀离心机/净化除铁槽/银电解槽/金电解槽等；火法冶炼设备165种新增侧吹炉/底吹炉/顶吹炉/三菱炉/卡尔多炉/多膛炉/沸腾焙烧炉/回转干燥窑/烧结机/球团竖炉/电弧炉/矿热炉/LF精炼炉/连铸机/热轧机/冷轧机/阳极浇铸机/阴极剥片机/捞渣机/转炉煤气回收系统/制氧机/氧枪系统/汽化冷却系统/电除尘器/脱硫塔/脱硝装置/冶金桥式起重机/钢包回转台等）
- **v0.1.91**：**矿山设备现场记录自动生成（针对矿山设备特点优化现场记录模板）**（新增app/mining_field_record.py；8种现场记录类型施工日志/设备开箱检验记录/隐蔽工程验收记录/设备安装记录/设备试运转记录/安全检查记录/吊装作业记录/焊接记录各含完整字段定义14-24项；8种典型设备专用记录要点球磨机/半自磨机/颚式破碎机/高压釜/闪速炉/浮选机/浓缩机/压滤机各含开箱/安装/隐蔽/试运转专用要点含具体质量标准数值；generate_field_record自动填充设备信息和专用要点生成现场记录；get_record_types获取所有记录类型；get_record_template获取指定类型模板；get_equipment_record_points获取设备专用要点；新增/api/mining-field-record/{types,template,generate,equipment-points}端点；前端新增矿山现场记录区）
- **v0.1.90**：**矿山设备AI助手优化（针对矿山设备特点优化问答提示词）**（新增app/mining_ai_assistant.py；7种专业问答模式施工方案咨询/吊装方案咨询/技术交底咨询/安全咨询/质量咨询/故障诊断咨询/通用咨询各含专业系统提示词；generate_ai_prompt按模式+设备类型+工艺流程生成专业问答提示词；generate_equipment_specific_prompt针对6种典型设备球磨机/半自磨机/颚式破碎机/高压釜/闪速炉/浮选机生成安装/调试/维护/故障/安全/通用提示词含关键技术要点和常见故障；get_ai_modes获取所有问答模式；get_mode_system_prompt获取指定模式系统提示词；新增/api/mining-ai/{modes,prompt,equipment-prompt}端点；前端新增矿山AI助手优化区）
- **v0.1.89**：**矿山设备资料完整性检查（按工艺流程检查各系统资料）**（新增app/mining_completeness.py；7大工艺流程资料要求清单破碎/磨矿/选别/脱水/火法冶炼/湿法冶炼/公用辅助各含系统级必备/可选资料20-25项和设备专用资料；破碎机/球磨机/半自磨机/浮选机/磁选机/浓缩机/压滤机/闪速炉/转炉/阳极炉/余热锅炉/高压釜/萃取箱/电积槽/蒸发器/空压机等20+种设备专用资料清单；check_process_completeness按工艺流程检查资料完整性标记缺失必备/可选资料按严重程度排序；_doc_exists模糊匹配支持精确/包含/关键词匹配；_generate_todo_list生成待补充资料清单按优先级排序；get_process_doc_requirements获取指定工艺流程资料要求；新增/api/mining-completeness/{check,requirements}端点；前端新增矿山资料完整性检查区）
- **v0.1.88**：**矿山设备施工进度计划自动生成（按工艺流程排程）**（新增app/mining_schedule.py；7大工艺流程施工阶段定义破碎/磨矿/选别/脱水/火法冶炼/湿法冶炼/公用辅助各含10-15个施工阶段含工期和依赖关系；设备类型到施工阶段映射60+种设备；generate_mining_schedule按工艺流程自动排程考虑设备依赖关系和并行施工；_add_workdays/_workday_diff工作日计算支持5/6/7天工作制；_calculate_critical_path关键路径分析；_check_schedule_warnings施工进度预警含工期过长/高温熔融/腐蚀介质预警；generate_gantt_svg生成甘特图SVG含时间轴月份刻度流程分色阶段条形图；get_schedule_stats进度统计；新增/api/mining-schedule/{generate,gantt,stats}端点；前端新增矿山施工进度计划区含甘特图展示）
- **v0.1.87**：**多电脑并库时矿山设备数据合并**（新增app/mining_equipment_merge.py；基于矿山设备知识库的设备类型识别；设计院编号与厂家编号映射合并；跨车间设备合并；设备空间位置合并；设备状态合并；自动去重位号精确匹配>设计院编号匹配>厂家编号匹配>名称+型号相似>名称高度相似候选；三种冲突策略latest/keep_existing/manual；合并日志保留100条；待人工确认pending管理；merge_stats统计；check_mining_equipment_integrity完整性检查位号唯一性/设备类型知识库检查/空间位置完整性/车间分配/设计院编号冲突/厂家编号冲突；新增/api/mining-equipment-merge/{merge,merge-file,pending,resolve/{id},log,stats,integrity}端点）
- **v0.1.86**：**矿山设备竣工资料组卷优化（按工艺流程组卷）**（新增app/mining_archive_organize.py；7大工艺流程破碎/磨矿/选别/脱水/火法冶炼/湿法冶炼/公用辅助；10个资料阶段开箱→基础→安装→隐蔽→配管→电气→仪表→试运转→试验→资料；按工艺流程自动组卷统计每卷设备数资料数完成率；卷册目录/设备清单/移交单生成；新增/api/mining-archive/{process-flow,organize,catalog,process-equipment,transmittal}端点）
- **v0.1.85**：**矿山设备施工方案/吊装方案模板优化**（新增app/mining_plan_templates.py；8种典型矿山设备专用施工方案破碎机/球磨机/半自磨机/浮选机/高压釜/闪速炉/转炉/余热锅炉各含方案大纲关键要点质量控制安全注意事项人员配置机具配置；8种专用吊装方案含吊装方法吊车选型吊点索具吊装顺序；生成方案自动关联设备空间位置标高>10m增加高处作业注意事项；新增/api/mining-plan/{types,construction,lifting}端点）
- **v0.1.84**：**矿山/选矿/冶炼设备内容扩充**（新增app/mining_equipment.py矿山设备知识库；4大分类205种设备矿山设备39种/选矿厂48种/湿法冶炼48种/火法冶炼70种；8类工程要点吊装参数/技术交底/隐蔽工程/开箱验收/设计变更/货损/施工日志；11个模块合并矿山设备数据lifting_plan/technical_disclosure/concealment_record/unboxing_record/design_change/damage_report/site_log/installation_plan/completion_archive/archive_enhanced/equipment_types；新增/api/mining-equipment/{categories,category,lifting-params}端点）
- **v0.1.83**：**设备安装位置与竣工资料联动增强**（新增app/archive_enhanced.py；10类设备竣工资料要求清单；generate_archive_checklist竣工资料清单根据设备状态判断资料是否应该已完成；check_archive_integrity完整性检查标记缺失必备/可选资料按严重程度排序；organize_archive_volumes按车间组卷；update_archive_doc_status更新资料状态；get_archive_summary总览；新增/api/archive-enhanced/{checklist,integrity,organize,summary,update-doc,requirements}端点）
- **v0.1.82**：**设备安装位置与施工进度联动增强**（新增app/progress_enhanced.py；analyze_critical_path关键路径分析；check_progress_warnings施工进度预警；optimize_installation_order施工顺序优化地下/低位/中位/高位四阶段；get_progress_dashboard施工进度总览；update_device_status_with_position更新设备状态带位置联动；新增/api/progress-enhanced/{critical-path,warnings,optimize-order,dashboard,update-status}端点）
- **v0.1.81**：**多电脑并库时货损报告合并**（新增app/damage_report_merge.py；自动去重基于MD5；三种冲突策略latest/keep_existing/manual；合并常见损坏部位/损坏原因分析/处理措施/索赔要求；合并后自动触发完整性检查；新增/api/damage-report-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.80**：**多电脑并库时设计变更合并**（新增app/design_change_merge.py；自动去重；三种冲突策略；合并常见变更类型/影响分析/处理措施/验收要求；合并后自动触发完整性检查；新增/api/design-change-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.79**：**多电脑并库时隐蔽工程验收记录合并**（新增app/concealment_merge.py；自动去重；三种冲突策略；合并隐蔽部位/检查项目/质量标准/验收依据/环境注意事项；合并后自动触发完整性检查；新增/api/concealment-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.78**：**多电脑并库时开箱验收记录合并**（新增app/unboxing_merge.py；自动去重；三种冲突策略；合并附件清单/技术资料/缺件清单/损坏件清单；合并后自动触发完整性检查；新增/api/unboxing-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.77**：**设备安装位置与货损报告联动**（新增app/damage_report.py；10类设备货损要点；generate_damage_report完整要素含报告编号/货损描述/常见损坏部位/损坏原因分析/处理措施/索赔要求/损坏程度/责任认定/参加人员；新增/api/damage-report/{generate,update,list,stats,points}端点）
- **v0.1.76**：**设备安装位置与设计变更联动**（新增app/design_change.py；10类设备设计变更要点；generate_design_change完整要素含变更编号/变更原因/常见变更类型/影响分析/处理措施/验收要求/变更状态/参加人员；新增/api/design-change/{generate,update,list,stats,points}端点）
- **v0.1.75**：**多电脑并库时施工日志合并**（新增app/site_log_merge.py；自动去重基于MD5；三种冲突策略；合并施工内容/人员配置/机具设备/材料使用/问题及处理/明日计划；合并后自动触发完整性检查；新增/api/site-log-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.74**：**设备安装位置与隐蔽工程验收记录联动**（新增app/concealment_record.py；10类设备隐蔽工程内容；generate_concealment_record完整要素含验收依据/环境注意事项/设备类型特殊注意事项/参加人员4方；新增/api/concealment-record/{generate,update,list,stats,content}端点）
- **v0.1.73**：**设备安装位置与开箱验收记录联动**（新增app/unboxing_record.py；10类设备开箱验收要点；generate_unboxing_record完整要素；新增/api/unboxing-record/{generate,update,list,stats,points}端点）
- **v0.1.72**：**多电脑并库时竣工资料合并增强**（新增app/archive_merge_enhanced.py；按车间/标高分组合并；新增/api/archive-merge-enhanced/{merge,merge-file,pending,resolve,log,stats,integrity,group-workshop,group-elevation}端点）
- **v0.1.71**：**设备安装位置与施工日志联动**（新增app/site_log.py；10类设备施工日志模板；generate_site_log；新增/api/site-log/{generate,list,stats,template}端点）
- **v0.1.70**：**设备安装位置与技术交底联动**（新增app/technical_disclosure.py；10类设备技术交底模板；generate_technical_disclosure；新增/api/technical-disclosure/{generate,list,stats,template}端点）
- **v0.1.69**：**多电脑并库时施工进度合并**（新增app/schedule_merge.py；合并施工进度数据；新增/api/schedule-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.68**：**设备安装位置与吊装方案联动**（新增app/lifting_plan.py；10类设备吊装参数；generate_lifting_plan；新增/api/lifting-plan/{generate,list,stats,params}端点）
- **v0.1.67**：**设备安装位置与竣工资料联动**（新增app/completion_archive.py；10类设备竣工资料要求；generate_completion_archive；新增/api/completion-archive/{device,all,stats,missing,update-doc,requirements}端点）
- **v0.1.66**：**多电脑并库时空间模型合并**（新增app/spatial_merge.py；合并空间模型数据；新增/api/spatial-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.65**：**设备安装位置与施工方案联动**（新增app/installation_plan.py；generate_installation_plan；get_device_spatial_info；新增/api/installation-plan/{generate,spatial-info,list,stats}端点）
- **v0.1.64**：**设备安装位置与施工进度联动**（新增app/construction_schedule.py；auto_schedule_devices按车间→关键设备→标高→x排序；generate_gantt_svg甘特图；设备状态管理；新增/api/construction-schedule/{auto,gantt,stats,status,workshops}端点）
- **v0.1.63**：**多电脑并库设备关系合并**（新增app/relations_merge.py；relations.py新增save_relations；合并设备关系数据；新增/api/relations-merge/{merge,merge-file,pending,resolve,log,stats,integrity}端点）
- **v0.1.62**：**设备安装位置三维可视化增强（等轴测视图）**（spatial_visualization.py新增3d/isometric等轴测视图；3d/views多视角）
- **v0.1.61**：**设备位置按标高分层可视化**（spatial_visualization.py新增elevation/list,elevation/layer,elevation/stack按标高分层）
- **v0.1.60**：**施工计划与设备数据联动增强**（docgen增加辅助函数，全部10类工程文档完成设备数据联动增强）
- **v0.1.59**：**多电脑并库竣工资料合并**（新增app/archive_merge.py；合并竣工资料数据；新增/api/archive-merge/{scan,merge,pending,resolve,log,stats}端点）
- **v0.1.58**：**设备安装位置与管线联动可视化**（新增app/spatial_visualization.py；SVG/HTML可视化设备位置和管线连接）
- **v0.1.57**：**竣工资料设备数据联动增强**（docgen竣工资料模板增加设备数据预填）
- **v0.1.56**：**货损报告设备数据联动增强**
- **v0.1.55**：**设计变更设备数据联动增强**
- **v0.1.54**：**施工日志设备数据联动增强**
- **v0.1.53**：**隐蔽工程验收记录设备数据联动增强**
- **v0.1.52**：**开箱验收记录设备数据联动增强**
- **v0.1.51**：**技术交底设备数据联动增强**
- **v0.1.50**：**吊装方案设备数据联动增强**
- **v0.1.49**：**施工方案设备数据联动增强**
- **v0.1.48**：**竣工资料自动组卷增强**
- **v0.1.47**：**设备间管线/连接关系**（新增app/piping_network.py；自动识别设备间管线连接；新增/api/piping/{build,pipes,connections,device/{tag},pipe/{pipe_no},stats}端点）
- **v0.1.46**：**施工日志自动生成**（新增app/construction_log.py；aggregate/list/save/generate/stats/generate-enhanced；新增/api/construction-log/{aggregate,list,{date},save,generate,stats,generate-enhanced}端点）

- **v0.1.45**：**设备台账多版本合并去重**（从所有解析文件提取设备清单Excel台账行/CAD图块/OCR铭牌；同一设备跨版本识别：位号精确匹配0.95>位号别名匹配0.85>名称+型号相似0.75>名称高度相似候选0.5；多版本合并最新版为准字段取并集冲突留人工确认；相同设备不同名称/编号自动辨认；字段冲突如重量不同默认取最新版可人工选择旧版；待确认匹配对支持确认合并/拒绝独立/合并为新设备；新模块app/equipment_merge.py；新增/api/equipment-merge/{run,list,pending,confirm/{index},resolve-conflict,stats}端点）
- **v0.1.44**：**CAD图纸自动提取坐标增强**（CAD文字标注TEXT/MTEXT中的位号自动关联坐标x,y（之前cad_text无坐标）；图块无位号属性时自动查找附近300mm范围内的文字标注关联位号（cad_block_nearby，置信度0.6）；从CAD图纸自动提取标高标注EL+xxx/±0.000/+5.500，关联到500mm范围内的设备（elevation_hint）；坐标来源分级置信度：cad_block=0.9/cad_block_nearby=0.6/cad_text=0.4；多图纸同一设备坐标合并（cad_positions含confidence+elevation）；空间模型z坐标回退使用CAD附近标高标注（z_source=cad_nearby，置信度0.5）；relations._equipment_from_cache CAD分支全面增强）
- **v0.1.43**：**群聊天文件关联设备人工确认**（群聊提及但不在设备图谱中的位号进入候选列表；前端⑤页群聊关联区显示候选设备+提及证据+话题；支持人工确认（指定车间后加入正式设备图谱并重建关系）和拒绝（不再提示，持久化到rejected_candidates.json）；重建图谱时自动跳过已拒绝的候选；新增/api/chat/{candidates,candidate/{tag}/confirm,candidate/{tag}/reject,rejected}端点；relations新增list_chat_candidates/confirm_chat_candidate/reject_chat_candidate/list_rejected_candidates函数）
- **v0.1.42**：**施工方案/吊装方案模板优化**（根据设备类型自动选择施工方案内容：泵/压缩机/换热器/塔器/容器/反应器/工业炉/输送设备/电动机等10类设备各有专属施工步骤；位号前缀识别（P=泵/C=压缩机/E=换热器/T=塔器/V=容器等HG/T 20519标准）+设备名称关键词识别；吊装方案根据设备重量自动选择吊装方法和吊车型号（≤2t手动葫芦/≤5t 8t汽车吊/≤25t 25t汽车吊/≤50t 50t汽车吊/≤100t 100t汽车吊或履带吊/≤200t 150t履带吊/>200t 300t以上履带吊）；根据重量自动选择吊索具规格；施工方案生成含施工步骤+质量控制章节；新模块app/equipment_types.py）
- **v0.1.41**：**设备位置人工确认界面**（位置待确认的设备可手动指定x/y/z坐标、车间归属、标高；修改后自动重新计算相邻设备和统计；coord_status从'位置待确认'变为'人工确认'；支持车间变更（从旧车间移除+加入新车间）；新增/api/spatial/device/{tag}/update、/api/spatial/device/{tag}/confirm、/api/spatial/pending端点；⑤页空间结构区位置待确认设备显示编辑按钮+弹出表单；spatial_model新增update_device_location/confirm_device/_update_stats函数）
- **v0.1.40**：**多电脑并库时现场记录去重合并**（本地拉取追踪 data/field_pulled.json，已拉取过的现场记录自动跳过（force=true强制重拉）；多台电脑对同一条现场记录的分析结果在云库侧合并——高置信度覆盖类型/数据，缺失字段取并集；分析来源节点追踪 record_analyze_sources；pull-field 返回 skipped/total_pulled 去重统计；新增/api/cloud/field-pulled 和 /api/cloud/field-pulled/clear 端点；回写分析结果时携带 node_name）
- **v0.1.39**：**资料自动关联到设备/车间**（已生成的工程资料自动关联到对应设备和车间；关联来源：生成时传入的设备/车间 > 文件名中的位号/车间 > docx内容中的位号/车间；archive._save_generated保存时自动登记；支持扫描所有已生成资料批量登记；完整性检查用关联关系精准判断设备级/车间级资料是否存在；新增/api/doc-relations/{list,device/{tag},workshop/{ws},scan}端点；新模块app/doc_relations.py）
- **v0.1.38**：**设备标高/楼层 z 坐标补充**（从设备台账Excel的标高/楼层列、CAD图纸EL/±0.000标注、OCR铭牌中提取设备安装标高；支持EL+100.000/±0.000/5.5m/3层/2F/二楼等多种格式解析；楼层按标准层高3m换算为标高；高置信度覆盖低置信度；空间结构模型从2D(x,y)升级为3D(x,y,z)，每台设备含z坐标+z来源+z置信度+z备注；AI空间摘要包含标高信息；⑤页空间结构区显示每台设备z坐标（绿/黄/红按置信度）+标高统计；新增/api/elevation/map端点；新模块app/elevation.py）
- **v0.1.37**：**手机端现场记录直接生成**（手机端上传照片/语音/文字后，工作台拉取现场资料时自动调用field_record分析记录类型（开箱/隐蔽/施工日志等10类）+提取关键字段预填+列出缺失字段，分析结果回写云库；cloud_server新增/api/cloud/field-record-result和field-record-generate端点存储分析结果和生成状态；⑨页现场清单显示每条记录的识别类型+缺失字段+是否已生成；手机端field-list返回分析结果，户外可见）
- **v0.1.36**：**资料完整性检查**（按工程6个阶段：施工准备/设备到货/施工过程/吊装作业/设计变更/竣工验收，自动检查资料完整性；区分项目级/车间级/设备级三个维度；每台设备应有开箱验收记录，每个车间应有施工日志+隐蔽验收记录；缺失项按优先级（高/中）列出待补充清单；各阶段完成度进度条；从已生成资料+已上传资料两个来源判断已有；新增app/completeness_check.py与/api/completeness/{check,todo,phase-status}；⑧页资料完整性检查区）
- **v0.1.35**：**设备安装位置空间关系深化**（基于CAD坐标+设备台账+车间划分建立AI可读类3D空间结构：车间→设备层级，每台设备有坐标(x,y,z预留)、坐标状态（图纸标注/台账记录图纸未标注/位置待确认）、来源类型、相邻设备（15米内自动计算）；台账有但图纸未标注的设备单独标记不丢失；车间内设备按坐标排序；生成AI可读空间结构文本摘要供外部Agent理解；relations重建后自动构建并保存data/spatial_model.json；新增app/spatial_model.py与/api/spatial/{structure,device/{tag},workshop/{ws},ai-summary}；⑤页空间结构区+AI摘要按钮）
- **v0.1.34**：**群聊天文件自动关联**（上传微信群/QQ群聊天记录导出文件TXT/HTML/CSV，自动解析每条消息（时间戳+发送人+内容），提取涉及的设备位号、车间、8类事项关键词（到货/安装/验收/问题/变更/安全/进度/资料），按设备/车间/事项生成摘要；群聊提及但不在台账中的设备进入人工确认；群聊提及的车间自动补充到车间列表；scanner解析后自动检测群聊文件并解析；relations图谱集成；新增app/chat_parser.py与/api/chat/{analyze,list}；⑤页群聊关联区）
- **v0.1.33**：**现场记录快速生成**（手机端照片/OCR/语音/文字自动识别记录类型：开箱验收/隐蔽验收/施工日志/技术交底/货损报告等10类；自动提取位号/车间/日期/人员/结果/箱单号等关键字段预填模板；缺失字段列出提醒，补充后生成Word；支持手动修改类型；新增app/field_record.py与/api/field-record/{analyze,generate}；⑥页现场记录快速生成区）
- **v0.1.32**：**多电脑并库冲突合并细化**（文件版本对照表：同名不同内容自动建立多版本，按时间戳以最新版为准；时间戳相同或缺失进待人工确认；同SHA256自动去重；scanner解析后登记版本，packager导入.fglib时登记来源节点版本；人工指定最新版API；①页版本对照表+冲突确认区；新增app/version_manager.py与/api/versions/{list,conflicts,set-latest}）
- **v0.1.31**：**设计院编号与厂家编号自动映射**（同一设备不同编号体系自动关联：CAD块属性/台账行同时标注设计院位号+厂家编号时提取映射对；以设计院位号为主键合并设备，厂家编号作为别名；高置信（CAD块≥0.8）直接确认，低置信（台账行0.6）进待人工确认；人工确认/拒绝API；⑤页映射确认表；新增app/tag_alias.py与/api/tag-alias/{list,confirm,reject}）
- **v0.1.30**：**施工方案/吊装方案辅助生成增强**（关键数据从解析库深度预填：车间设备清单+设备级车间归属+向量库检索设备重量参数+平台库现行规范正文引用；缺失字段列出待补充；吊装方案专项参数：设备重量/吊装半径/吊装高度/吊车型号/吊车站位/吊索具，生成Word含吊装参数专章；前端预填自动写入表单+缺失标红+规范引用提示；docgen.prefill_from_db新函数）
- **v0.1.29**：**设备箱单跨车间自动归类**（设备级车间归属：台账行"车间"列自动登记每台设备→车间，位号前缀推断兜底（P-101→1号车间），人工指定最高优先；跨车间箱单文件本身归未归车间但设备正确分到各车间；relations 图谱用设备登记车间覆盖投票；新增app/device_workshop.py与/api/device-workshop/{list,assign,rebuild}，⑤页设备车间归属表）
- **v0.1.28**：**平台规范库联网核验升级**（多源聚合核验：自定义端点＞openstd＞工标网csres＞标准分享网bzfxw＞百度搜索摘要，多数票决状态+置信度+来源记录；废止/待核验条目提供搜索最新版快捷链接；单条立即核验 /api/platform/verify；核验元数据 verify_source/confidence/sources 持久化）
- **v0.1.27**：**车间资料自动划分增强**（上传/扫描后自动识别车间：CAD标题栏＞文件名＞正文关键词；无法确认进未归车间；单文件/批量人工指定车间，重建图谱即生效；新增app/workshop_assign.py与/api/workshop/{list,assign,batch-assign,re-auto}）
- **v0.1.26**：**手机语音自动转写**（拉取现场语音自动转文字成现场记录入资料库：本机 faster-whisper 或 AI 网关 /transcribe 自动转写，转写文本回写云库手机端可见；未装模型/未配置网关→待转写清单人工补录；新增 /api/cloud/field-transcribe）
- **v0.1.25**：**⑤页关系网络图**（车间↔图纸↔设备三列分层确定性布局，点击节点高亮关联子网，图例+容量控制；替代纯表格直观呈现设备-车间-图纸关联）
- **v0.1.24**：**竣工资料自动组卷**（生成资料自动存档 data/generated_docs；按 8 卷归档结构归卷，缺失类型列出待补；导出 zip 含卷内目录.xlsx；新增 /api/archive/status、/api/archive/export）
- **v0.1.23**：**手机现场照片自动 OCR 铭牌 → 候选设备确认**（现场照片铭牌自动识别位号/型号/参数/厂家；未在图纸与台账的位号进入『铭牌候选设备』待人工确认归属车间，确认后挂载到图谱 layout 持久化；拉取现场照片后铭牌摘要自动回写云库，手机端清单可见）
- **v0.1.22**：**多文件夹后台批量上传**（①页新增文件夹选择+拖放区：多文件夹自动分批（每批20个）串行上传，切换页面不断；关页后已传文件已入库，重开重选文件夹自动跳过已传（localStorage 断点）；上传接口 SHA256 去重+索引登记+上传人留痕）
- **v0.1.21**：**上传失败管理**（①页新增失败/待处理清单：失败文件可单个/全部多次重试、单个删除、清空；重试 3 次仍失败自动转『待处理』供人工检查；新增 /api/scan/failed-list、/api/scan/retry-failed/{sha}、/api/scan/failed/delete、/api/scan/failed/clear）
- **v0.1.20**：**部署手册**（docs/部署手册.md：电脑端/云端/手机端/AI 网关/多电脑并库/规范核验配置/常见问题/数据迁移全流程，新电脑按手册 15 分钟可上线）
- **v0.1.19**：**手机端 AI 助手桥接**（云库新增 /api/cloud/ai-chat：手机 → 云库 → 电脑工作台 AI 助手，可离线问答与生成 Word 资料；配置 cloud_server AI_WORKBENCH_ENDPOINT 指向工作台即启用，未配置自动降级云库轻量检索；云库检索增强：大小写不敏感+中文二连字计分）
- **v0.1.18**：**计划页一键生成联动**（⑧计划页每项资料点『去生成』→ 弹窗自动带出车间设备清单+规范引用+必填字段可编辑 → 一键生成 Word 下载；新增 /api/docplan/generate；缺部分前置的资料也可生成，缺字段红字待补）
- **v0.1.17**：**资料生成引用规范正文**（docgen.std_citations：生成施工/吊装方案等资料时，从平台库检索现行/待核验规范的正文条款写入『编制依据』——引用的是规范内容而非仅标准号；无规范时红字提示人工补充）
- **v0.1.16**：**AI 助手窗口**（⑩页，app/ai_chat.py：自动多库检索=项目库+平台库+工程关系+资料待办；输入含模板名即离线生成 Word 工程资料——解析库预填+自动提取用户关键数据，缺失字段列出待补；配置 AI_GATEWAY_ENDPOINT 并设 AI_MODE=gateway 可升级联网 AI 问答；API：/api/ai/chat、/api/ai/status）
- **v0.1.15**：**平台库联网自动核验**（app/std_verify.py 标准核验适配器：优先自定义核验端点 PLATFORM_SEARCH_ENDPOINT，内置全国标准信息公共服务平台 openstd 尽力而为检索；**首次上传规范即核验**——现行立即标注、废止立即标注最新版号提示替换、无法核验进待核验人工兜底；每 6 个月到期自动核验：现行续期/废止标注最新版/未知待核验，确保 AI 引用的是现行规范正文）
- **v0.1.14**：**手机端对接云库**（云库新增手机现场上传 field-upload——免登录、只写上传人姓名、同一手机不再确认，照片/语音/文字按内容 SHA256 去重；工作台新增⑨云库页：连接状态/云库文件/现场上传统计、云端现场清单、一键"拉取现场资料并解析"自动入库；docs/手机端对接云库.md 提供手机端检索+上传完整对接说明；修复云端下载中文文件名 latin-1 崩溃）
- **v0.1.13**：**CAD 多图纸深度联动**（⑤页图纸网络：每张 CAD 图提取图号/图名/车间/覆盖设备/坐标，图纸间自动互引——共享设备＋全场图↔车间图＋同套图号（如 A-101/A-102 同属 A 套）；设备→车间映射表以设计院图纸（cad）为准、台账次之，平票冲突自动进人工确认队列；新增 /api/relations/drawings、/api/relations/layout 两个接口；AI 空间摘要同步增强）
- **v0.1.12**：**工程资料深度生成**（资料生成计划⑧页：按解析库自动判断"库里已有什么/每类资料缺什么"，缺项列出清单进待办，补进库后自动转可生成；人工可按现场进度登记资料任务，支持完成/删除；docgen 模板从 5 类扩展到 10 类——新增施工计划、施工日志、设计变更、货损报告、竣工资料，全部优先 Word、缺失必填字段红字『待补充』；预填增强自动带出设备清单＋平台规范引用；新增 docplan API 4 个；预留联网模板优化端点 TEMPLATE_SEARCH_ENDPOINT）
- **v0.1.11**：**云端合并主库**（cloud_server/ 独立 FastAPI 服务：接收各电脑解析队列上传的 payload 按 SHA256 去重合并为一个完整云库；云库在线检索 `/api/cloud/search` 供手机端/外部 Agent 户外读取；云库↔工作台 `.fglib` 双向互导；Bearer 鉴权；一键部署 run_server.bat + 对接文档；手机端只需配置云库地址即可读取全部项目资料）
- **v0.1.10**：**平台级规范库**（国标/规范/通用文件独立建库，所有项目共享）：自动提取标准号/标准名（GB/GB-T/JGJ/HG-T/DL-T/JB-T/ISO 等 20 类）；上传时立即登记有效期，每 6 个月（可配）自动提醒核验；配置 PLATFORM_SEARCH_ENDPOINT 后可联网自动核验并搜索最新版替换（废止自动标注）；AI 检索项目库时可同时检索平台库（引用规范正文内容而非名称）；状态人工可改（现行/待核验/废止）；新电脑安装时导出 .fpglib 平台库包导入即可复用；新增⑦平台规范库页 + 7 个 API
- **v0.1.9**：**解析库打包/多机合并**（多台电脑各自解析 → 导出 .fglib 库包 → 导入合并为一个完整库）：库包含 index + 解析缓存 + 关联图谱 + manifest（fglib-v1 格式）；导入按 SHA256 去重合并（同一文件自动跳过，含 skipped 项）；同名不同内容以导入库为准覆盖、旧版备份 .conflict.json；本地记录升级（包内 parsed 覆盖本地 skipped）；合并后自动重建关联图谱；新增 /api/library/export、/api/library/import 与前端①页"库导出/合并"区；修复上传队列目录被删后 enqueue 报错（每次确保目录存在）
- **v0.1.8**：OCR 铭牌识别（现场照片→PaddleOCR 提取铭牌位号/参数/厂家/车间；实体 4 类：设备/参数/厂家/车间；OCR 照片自动挂接设备与车间，支持三源关联 CAD+台账+照片；PaddleOCR 2.x/3.x 兼容；未装依赖自动降级）
- **v0.1.7**：工程资料生成引擎（5 类方案：施工方案/吊装方案/技术交底/开箱验收记录/隐蔽工程验收记录；可从关联图谱自动预填车间设备；缺失必填字段红字『待补充』标注；按模板生成 Word 下载，人工打印签字；新增 ⑥ 方案生成页 + types/prefill/generate 3 API）
- **v0.1.6**：设备间距与空间关系（同图设备两两距离按真实毫米坐标换算为米，标题栏比例展示；距离摘要写入向量库支持"某设备距某设备多远"问答；新增 /api/relations/distances 与车间详情距离表；前端⑤页新增设备间距列表）
- **v0.1.5**：**多图纸联动关联图谱**（全场布置图↔车间图↔设备台账）：自动识别车间（文件名/标题栏/正文，"1车间/二号车间"归一化）；图纸类型分类（全场布置图/车间图纸/台账/计划）；全场图内车间定位坐标；设备位号跨图纸/台账关联（CAD 块属性↔台账行↔文本实体）；跨车间冲突/无归属进"待人工确认"；空间摘要写入向量库（AI 可按车间/坐标/设备问答）；新增"⑤ 关联图谱"页面与 3 个 API
- **v0.1.4**：CAD 深度解析（图框检测 / 标题栏图号图名比例设计等字段 / 设备块坐标与属性 / 尺寸标注测量值 / 图层统计 / 空间结构打底）；可选依赖自动探测（装好即启用）；`install-full.bat` 一键全套部署（核心+OCR+CAD）
- **v0.1.3**：PDF 表格提取（pdfplumber，含无边框表格文本策略兜底）；手动上传文件接口 `/api/upload-files`（浏览器/手机端直传，记录上传人，落盘→解析→向量化→队列一步完成）；前端上传区
- **v0.1.2**：Project 计划解析实测通过；Excel 同名列自动去重；上传/打包留痕记录查看
- **v0.1.1**：多文件夹批量扫描（每行一个路径）；失败文件人工重试；CAD 文本坐标记录（空间库打底）
- **v0.1.0（MVP）**：主链路（扫描→解析→向量化→队列→检索）打通；PDF/Word/Excel/Text 解析；实体位号提取；可选 OCR/CAD/Project；云端合并队列。

---
© 2026 胡繁荣 · 繁工AI（FanGong AI）· 工程蓝 #1E5AA8 / 安全橙 #FF7A00
