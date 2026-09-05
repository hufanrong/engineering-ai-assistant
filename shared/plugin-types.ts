// ---- plugin:engineering_document_parser_1 ----
// ============================================================
// 插件 engineering_document_parser_1 (工程台账/图纸文件解析) 的类型定义
// 由 get_plugin_ai_json 自动生成
// ============================================================

export interface EngineeringDocumentParserOneInput {
  /** 文件URL列表，目前仅支持上传一个文件 */
  fileUrl: string[];
}

/**
 * capabilityClient.load('engineering_document_parser_1').call<EngineeringDocumentParserOneOutput>('parseDocToMarkdown', input)
 * 直接返回此类型，无 .data 包装，直接解构使用：
 * const { content } = result;
 * 返回值形如：
 *   {"content":"示例文本"}
 */
export interface EngineeringDocumentParserOneOutput {
  /** [object Object] */
  content: string;
}
// ---- end:engineering_document_parser_1 ----

// ---- plugin:engineering_ledger_entity_extraction_1 ----
// ============================================================
// 插件 engineering_ledger_entity_extraction_1 (工程台账实体结构化提取) 的类型定义
// 由 get_plugin_ai_json 自动生成
// ============================================================

export interface EngineeringLedgerEntityExtractionOneInput {
  /** 待提取的工程台账文本 */
  text: string;
}

/**
 * capabilityClient.load('engineering_ledger_entity_extraction_1').call<EngineeringLedgerEntityExtractionOneOutput>('textToJson', input)
 * 直接返回此类型，无 .data 包装，直接解构使用：
 * const { entities } = result;
 * 返回值形如：
 *   {"entities":"示例文本"}
 */
export interface EngineeringLedgerEntityExtractionOneOutput {
  /** 实体列表的JSON数组字符串，每个元素包含code(实体编号)、name(实体名称)、model(型号)、spec(规格)、entityType(实体类型，取值equipment/pipe/valve/instrument/material) */
  entities: string;
}
// ---- end:engineering_ledger_entity_extraction_1 ----

// ---- plugin:mobile_voice_transcription_1 ----
// ============================================================
// 插件 mobile_voice_transcription_1 (移动端现场语音采集转文字) 的类型定义
// 由 get_plugin_ai_json 自动生成
// ============================================================
// ---- end:mobile_voice_transcription_1 ----

// ---- plugin:site_photo_structured_extraction_1 ----
// ============================================================
// 插件 site_photo_structured_extraction_1 (现场照片结构化提取) 的类型定义
// 由 get_plugin_ai_json 自动生成
// ============================================================

export interface SitePhotoStructuredExtractionOneInput {
  /** 图片 URL 列表，仅支持一张 */
  imageUrl: string[];
}

/**
 * capabilityClient.load('site_photo_structured_extraction_1').call<SitePhotoStructuredExtractionOneOutput>('imageToJson', input)
 * 直接返回此类型，无 .data 包装，直接解构使用：
 * const { location, extraInfo, title, ... } = result;
 * 返回值形如：
 *   {"location":"示例文本","extraInfo":"示例文本","title":"示例文本","content":"示例文本"}
 */
export interface SitePhotoStructuredExtractionOneOutput {
  /** 部位或位置，描述事件发生的具体位置或部位 */
  location: string;
  /** 其他关键信息，无则填空字符串 */
  extraInfo: string;
  /** 记录标题，简要概括现场记录的核心内容 */
  title: string;
  /** 记录完整内容描述，包含设备名称、编号、数量、施工部位、作业内容等关键信息 */
  content: string;
}
// ---- end:site_photo_structured_extraction_1 ----

// ---- plugin:engineering_database_agent_search_summary_1 ----
// ============================================================
// 插件 engineering_database_agent_search_summary_1 (工程资料库Agent检索结果摘要洞察) 的类型定义
// 由 get_plugin_ai_json 自动生成
// ============================================================

export interface EngineeringDatabaseAgentSearchSummaryOneInput {
  /** 工程领域检索查询词 */
  search_query: string;
  /** 检索命中的内容要点 */
  content_highlights?: string;
}

/**
 * capabilityClient.load('engineering_database_agent_search_summary_1').callStream<EngineeringDatabaseAgentSearchSummaryOneOutput>('searchSummary', input)
 * 每个 chunk 就是下面这个扁平对象，字段名与 EngineeringDatabaseAgentSearchSummaryOneOutput 一致，外面没有 data / choices / message 包装：
 *   {"summary":"示例文本"}
 * 返回值可能是 AsyncIterable<chunk>，也可能是 { output: AsyncIterable<chunk> }，取流前先归一化。
 * 逐段累加：
 *   for await (const chunk of stream) { result += chunk.summary ?? ''; }
 */
export interface EngineeringDatabaseAgentSearchSummaryOneOutput {
  /** [object Object] */
  summary: string;
}
// ---- end:engineering_database_agent_search_summary_1 ----