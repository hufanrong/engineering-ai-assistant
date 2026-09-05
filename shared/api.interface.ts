/* 前后端共享的类型写在这里 */

/* ==================== 记录状态 ==================== */

export const RECORD_STATUS = {
  COMPLETE: 'complete',
  PENDING_SUPPLEMENT: 'pending_supplement',
  PENDING_CLASSIFY: 'pending_classify',
} as const;
export type RecordStatus = (typeof RECORD_STATUS)[keyof typeof RECORD_STATUS];

export const RECORD_STATUS_LABELS: Record<string, string> = {
  [RECORD_STATUS.COMPLETE]: '完整',
  [RECORD_STATUS.PENDING_SUPPLEMENT]: '待补充',
  [RECORD_STATUS.PENDING_CLASSIFY]: '待分类',
};

/* ==================== 资料类型（13 大类） ==================== */

export const RECORD_TYPE = {
  OPENING_RECORD: 'opening_record',
  CONCEALED_RECORD: 'concealed_record',
  INSPECTION_BATCH: 'inspection_batch',
  EQUIPMENT_ARRIVAL: 'equipment_arrival',
  CONSTRUCTION_LOG: 'construction_log',
  MATERIAL_ARRIVAL: 'material_arrival',
  TEST_REPORT: 'test_report',
  MEASUREMENT_RECORD: 'measurement_record',
  DISCLOSURE: 'disclosure',
  DESIGN_CHANGE: 'design_change',
  DAMAGE_RECORD: 'damage_record',
  LEDGER: 'ledger',
  OTHER: 'other',
} as const;
export type RecordType = (typeof RECORD_TYPE)[keyof typeof RECORD_TYPE];

export const RECORD_CATEGORY_LABELS: Record<string, string> = {
  acceptance: '验收类',
  record: '记录类',
  concealed: '隐蔽类',
  test: '试验类',
  measurement: '测量类',
  disclosure: '交底类',
  change: '变更类',
  damage: '货损类',
  ledger: '台账类',
  other: '其他',
};

/* ==================== 文件 ==================== */

export const FILE_TYPE = {
  DWG: 'dwg',
  PDF: 'pdf',
  DOCX: 'docx',
  XLSX: 'xlsx',
  IMAGE: 'image',
  AUDIO: 'audio',
  TXT: 'txt',
  CHAT: 'chat',
  OTHER: 'other',
} as const;
export type ProjectFileType = (typeof FILE_TYPE)[keyof typeof FILE_TYPE];

export const FILE_SOURCE = {
  WEB_UPLOAD: 'web_upload',
  WEB_FOLDER: 'web_folder',
  MOBILE_PHOTO: 'mobile_photo',
  MOBILE_VOICE: 'mobile_voice',
  MOBILE_TEXT: 'mobile_text',
} as const;
export type FileSource = (typeof FILE_SOURCE)[keyof typeof FILE_SOURCE];

export const PARSE_STATUS = {
  PENDING: 'pending',
  PROCESSING: 'processing',
  SUCCESS: 'success',
  FAILED: 'failed',
  SKIPPED: 'skipped',
} as const;
export type ParseStatus = (typeof PARSE_STATUS)[keyof typeof PARSE_STATUS];

export const PARSE_STATUS_LABELS: Record<string, string> = {
  [PARSE_STATUS.PENDING]: '待解析',
  [PARSE_STATUS.PROCESSING]: '解析中',
  [PARSE_STATUS.SUCCESS]: '解析成功',
  [PARSE_STATUS.FAILED]: '解析失败',
  [PARSE_STATUS.SKIPPED]: '已跳过',
};

/* ==================== 实体 ==================== */

export const ENTITY_TYPE = {
  EQUIPMENT: 'equipment',
  PIPE: 'pipe',
  VALVE: 'valve',
  INSTRUMENT: 'instrument',
  MATERIAL: 'material',
  DRAWING: 'drawing',
  DOCUMENT: 'document',
  RECORD: 'record',
} as const;
export type EntityType = (typeof ENTITY_TYPE)[keyof typeof ENTITY_TYPE];

export const ENTITY_TYPE_LABELS: Record<string, string> = {
  [ENTITY_TYPE.EQUIPMENT]: '设备',
  [ENTITY_TYPE.PIPE]: '管道',
  [ENTITY_TYPE.VALVE]: '阀门',
  [ENTITY_TYPE.INSTRUMENT]: '仪表',
  [ENTITY_TYPE.MATERIAL]: '材料',
  [ENTITY_TYPE.DRAWING]: '图纸',
  [ENTITY_TYPE.DOCUMENT]: '文档',
  [ENTITY_TYPE.RECORD]: '记录',
};

export const MERGE_STATUS = {
  MERGED: 'merged',
  PENDING: 'pending',
  STANDALONE: 'standalone',
} as const;
export type MergeStatus = (typeof MERGE_STATUS)[keyof typeof MERGE_STATUS];

export const MERGE_STATUS_LABELS: Record<string, string> = {
  [MERGE_STATUS.MERGED]: '已归并',
  [MERGE_STATUS.PENDING]: '待确认',
  [MERGE_STATUS.STANDALONE]: '独立',
};

export const ALIAS_SOURCE_TYPE = {
  DESIGN_INSTITUTE: 'design_institute',
  MANUFACTURER: 'manufacturer',
  PROCUREMENT: 'procurement',
  ARRIVAL: 'arrival',
  MANUAL: 'manual',
} as const;
export type AliasSourceType =
  (typeof ALIAS_SOURCE_TYPE)[keyof typeof ALIAS_SOURCE_TYPE];

export const ALIAS_SOURCE_LABELS: Record<string, string> = {
  [ALIAS_SOURCE_TYPE.DESIGN_INSTITUTE]: '设计院',
  [ALIAS_SOURCE_TYPE.MANUFACTURER]: '厂家',
  [ALIAS_SOURCE_TYPE.PROCUREMENT]: '采购',
  [ALIAS_SOURCE_TYPE.ARRIVAL]: '到货',
  [ALIAS_SOURCE_TYPE.MANUAL]: '人工',
};

// ===================== 知识图谱 =====================

export interface GraphNode {
  id: string;
  name: string;
  code: string | null;
  entityType: string;
  workshopName?: string;
  aliasCount: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationshipType: string;
}

export interface GraphDataResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ===================== 资料库连接与 Agent 检索 =====================

export interface RepositoryStats {
  fileCount: number;
  entityCount: number;
  relationshipCount: number;
  recordCount: number;
  taskCount: number;
}

export interface PlatformLibInfo {
  standardsCount: number;
  materialsCount: number;
  processesCount: number;
}

export interface RepositoryInfo {
  projectId: string;
  projectName: string;
  apiEndpoint: string;
  searchApi: string;
  agentApiKey: string;
  localPaths: { database: string; files: string };
  stats: RepositoryStats;
  platformLib: PlatformLibInfo;
}

export interface RotateKeyResponse {
  agentApiKey: string;
}

export interface RagDocumentResult {
  sourceType: 'record' | 'file';
  title: string;
  content: string;
  recordType?: string;
  workshopName?: string;
  createdAt: string;
}

export interface RagEntityResult {
  id: string;
  name: string;
  code: string | null;
  entityType: string;
  aliases: string[];
}

export interface RagPlatformResult {
  id: string;
  libType: 'standard' | 'material';
  name: string;
  code?: string;
  extra?: string;
}

export interface RagSearchRequest {
  projectId: string;
  query: string;
  workshopId?: string;
}

export interface RagSearchResponse {
  documentResults: RagDocumentResult[];
  entityResults: RagEntityResult[];
  platformResults: RagPlatformResult[];
  summary: string;
}

// ===================== 平台级数据管理 =====================

export interface PlatformStandardItem {
  id: string;
  standardCode: string;
  name: string;
  publishDate?: string;
  category?: string;
  content?: string;
}

export interface CreatePlatformStandardRequest {
  standardCode: string;
  name: string;
  publishDate?: string;
  category?: string;
  content?: string;
}

export type UpdatePlatformStandardRequest = Partial<CreatePlatformStandardRequest>;

export interface PlatformMaterialItem {
  id: string;
  name: string;
  materialGrade?: string;
  spec?: string;
  standardCode?: string;
  category?: string;
}

export interface CreatePlatformMaterialRequest {
  name: string;
  materialGrade?: string;
  spec?: string;
  standardCode?: string;
  category?: string;
}

export type UpdatePlatformMaterialRequest = Partial<CreatePlatformMaterialRequest>;

export interface PlatformProcessItem {
  id: string;
  name: string;
  scope?: string;
  description?: string;
  category?: string;
}

export interface CreatePlatformProcessRequest {
  name: string;
  scope?: string;
  description?: string;
  category?: string;
}

export type UpdatePlatformProcessRequest = Partial<CreatePlatformProcessRequest>;

export interface PlatformListResponse<T> {
  items: T[];
  total: number;
}

export const PLATFORM_LIB_LABELS = {
  standard: '规范库',
  material: '材料库',
  process: '工艺库',
} as const;

export const MERGE_QUEUE_STATUS = {
  PENDING: 'pending',
  CONFIRMED_MERGE: 'confirmed_merge',
  CONFIRMED_SEPARATE: 'confirmed_separate',
  IGNORED: 'ignored',
} as const;
export type MergeQueueStatus =
  (typeof MERGE_QUEUE_STATUS)[keyof typeof MERGE_QUEUE_STATUS];

export const CONFLICT_STATUS = {
  PENDING: 'pending',
  RESOLVED_A: 'resolved_a',
  RESOLVED_B: 'resolved_b',
  RESOLVED_MANUAL: 'resolved_manual',
  IGNORED: 'ignored',
} as const;
export type ConflictStatus =
  (typeof CONFLICT_STATUS)[keyof typeof CONFLICT_STATUS];

/* ==================== 关系与图谱 ==================== */

export const RELATIONSHIP_TYPE = {
  LOCATED_IN: 'LOCATED_IN',
  REFERENCES: 'REFERENCES',
  CONTAINS: 'CONTAINS',
  MENTIONS: 'MENTIONS',
  CONNECTED_TO: 'CONNECTED_TO',
  BELONGS_TO: 'BELONGS_TO',
} as const;
export type RelationshipType =
  (typeof RELATIONSHIP_TYPE)[keyof typeof RELATIONSHIP_TYPE];

export const RELATIONSHIP_TYPE_LABELS: Record<string, string> = {
  [RELATIONSHIP_TYPE.LOCATED_IN]: '位于',
  [RELATIONSHIP_TYPE.REFERENCES]: '引用',
  [RELATIONSHIP_TYPE.CONTAINS]: '包含',
  [RELATIONSHIP_TYPE.MENTIONS]: '提及',
  [RELATIONSHIP_TYPE.CONNECTED_TO]: '连接',
  [RELATIONSHIP_TYPE.BELONGS_TO]: '属于',
};

/* ==================== 后台任务 ==================== */

export const TASK_TYPE = {
  PARSE: 'parse',
  TYPE_RECOGNIZE: 'type_recognize',
  ENTITY_EXTRACT: 'entity_extract',
  ENTITY_MERGE: 'entity_merge',
  AUDIO_TRANSCRIBE: 'audio_transcribe',
  IMAGE_EXTRACT: 'image_extract',
} as const;
export type TaskType = (typeof TASK_TYPE)[keyof typeof TASK_TYPE];

export const TASK_TYPE_LABELS: Record<string, string> = {
  [TASK_TYPE.PARSE]: '文档解析',
  [TASK_TYPE.TYPE_RECOGNIZE]: '类型识别',
  [TASK_TYPE.ENTITY_EXTRACT]: '实体提取',
  [TASK_TYPE.ENTITY_MERGE]: '实体归并',
  [TASK_TYPE.AUDIO_TRANSCRIBE]: '语音转写',
  [TASK_TYPE.IMAGE_EXTRACT]: '图片提取',
};

export const TASK_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  SUCCESS: 'success',
  FAILED: 'failed',
} as const;
export type TaskStatus = (typeof TASK_STATUS)[keyof typeof TASK_STATUS];

export const TASK_STATUS_LABELS: Record<string, string> = {
  [TASK_STATUS.PENDING]: '待执行',
  [TASK_STATUS.RUNNING]: '执行中',
  [TASK_STATUS.SUCCESS]: '成功',
  [TASK_STATUS.FAILED]: '失败',
};

/* ==================== 项目 ==================== */

export const PROJECT_STATUS = {
  ACTIVE: 'active',
  ARCHIVED: 'archived',
} as const;
export type ProjectStatus =
  (typeof PROJECT_STATUS)[keyof typeof PROJECT_STATUS];

export const PROJECT_STATUS_LABELS: Record<string, string> = {
  [PROJECT_STATUS.ACTIVE]: '进行中',
  [PROJECT_STATUS.ARCHIVED]: '已归档',
};

/* ==================== 分页 ==================== */

export interface PagedResponse<T> {
  items: T[];
  total: number;
}

// ===== 项目与车间管理 =====

export interface ProjectSummaryItem {
  id: string;
  name: string;
  code: string;
  status: string;
  workshopCount: number;
  fileCount: number;
  recordCount: number;
  pendingCount: number;
  createdAt: string;
}

export interface ProjectListResponse {
  items: ProjectSummaryItem[];
}

export interface CreateProjectRequest {
  name: string;
  code: string;
  description?: string;
}

export interface CreateProjectResponse {
  id: string;
  agentApiKey: string;
}

export interface UpdateProjectRequest {
  name?: string;
  code?: string;
  description?: string;
  status?: 'active' | 'archived';
}

export interface UpdateProjectResponse {
  id: string;
  name: string;
  code: string;
  description?: string;
  status: string;
}

export interface DeleteProjectResponse {
  id: string;
  deleted: true;
}

export interface ProjectDetailInfo {
  id: string;
  name: string;
  code: string;
  description?: string;
  status: string;
  createdAt: string;
}

export interface ProjectStatistics {
  workshopCount: number;
  fileCount: number;
  recordCount: number;
  entityCount: number;
  pendingMergeCount: number;
  pendingSupplementCount: number;
}

export interface WorkshopSummary {
  id: string;
  name: string;
  code: string;
  description?: string;
  sortOrder: number;
  fileCount: number;
  recordCount: number;
}

export interface WorkshopListResponse {
  items: WorkshopSummary[];
}

export interface CreateWorkshopRequest {
  name: string;
  code: string;
  description?: string;
  sortOrder?: number;
}

export interface UpdateWorkshopRequest {
  name?: string;
  code?: string;
  description?: string;
  sortOrder?: number;
}

export interface WorkshopMutationResponse {
  id: string;
}

// ===== 仪表盘 =====

export interface DashboardSummary {
  projectCount: number;
  workshopCount: number;
  fileCount: number;
  recordCount: number;
  pendingMergeCount: number;
  pendingSupplementCount: number;
  pendingConflictCount: number;
  pendingClassifyCount: number;
  approvalCount: number;
}

export interface DashboardActivity {
  id: string;
  kind: 'file' | 'record';
  title: string;
  recordType?: string;
  projectId: string;
  projectName: string;
  creatorId?: string;
  creatorName: string;
  createdAt: string;
}

export interface DashboardActivitiesResponse {
  items: DashboardActivity[];
}

// ===== 文件管理 =====

export interface CreateFileRequest {
  filename: string;
  fileUrl: string;
  fileType: string;
  fileSize: number;
  sha256: string;
  workshopIds: string[];
  source: string;
}

export interface CreateFileResponse {
  id: string;
  versionNo: number;
  isLatest: boolean;
  duplicated: boolean;
  message?: string;
}

export interface FileListItem {
  id: string;
  filename: string;
  fileType: string;
  fileSize: number;
  versionNo: number;
  isLatest: boolean;
  parseStatus: string;
  workshopNames: string[];
  creatorName: string;
  createdAt: string;
}

export interface FileListResponse extends PagedResponse<FileListItem> {}

export interface FileVersionItem {
  versionNo: number;
  filename: string;
  fileUrl: string;
  createdAt: string;
  creatorName: string;
}

export interface FileDetail {
  id: string;
  filename: string;
  fileUrl: string;
  fileType: string;
  fileSize: number;
  sha256: string;
  parseStatus: string;
  parseError?: string;
  versionNo: number;
  workshops: Array<{ id: string; name: string }>;
  relatedEntities: Array<{ id: string; name: string; code: string }>;
  versions: FileVersionItem[];
}

export interface TaskListItem {
  id: string;
  taskType: string;
  status: string;
  progress: number;
  message?: string;
  fileName?: string;
  recordTitle?: string;
  createdAt: string;
}

export interface TaskListResponse extends PagedResponse<TaskListItem> {}

export interface TaskRetryResponse {
  id: string;
  status: string;
}

// ===== 现场记录 =====

export interface RecordField {
  key: string;
  label: string;
}

export interface RecordTypeConfigItem {
  recordType: string;
  displayName: string;
  category: string;
  requiredFields: RecordField[];
  keywords: string[];
}

export interface RecordTypeConfigResponse {
  items: RecordTypeConfigItem[];
}

export interface RecordListItem {
  id: string;
  title: string;
  recordType: string;
  recordTypeName: string;
  projectId: string;
  projectName: string;
  workshopName?: string;
  recordDate?: string;
  status: string;
  completeness: number;
  creatorName: string;
  createdAt: string;
}

export interface RecordListResponse extends PagedResponse<RecordListItem> {}

export interface RecordDetail {
  id: string;
  projectId: string;
  title: string;
  recordType: string;
  recordTypeName: string;
  content: string;
  recordDate?: string;
  location?: string;
  status: string;
  completeness: number;
  missingFields: RecordField[];
  typeConfidence: number;
  typeModified: boolean;
  workshop?: { id: string; name: string };
  relatedEntities: Array<{
    id: string;
    name: string;
    code: string;
    entityType: string;
  }>;
  attachments: Array<{ id: string; filename: string; fileUrl: string }>;
}

export interface UpdateRecordRequest {
  recordType?: string;
  title?: string;
  content?: string;
  location?: string;
  recordDate?: string;
}

export interface UpdateRecordResponse {
  id: string;
  recordType: string;
  status: string;
  completeness: number;
}

export interface SupplementRequest {
  supplements: Array<{ key: string; value: string }>;
}

export interface SupplementResponse {
  id: string;
  status: string;
  completeness: number;
  missingFields: RecordField[];
}

export interface CreateRecordRequest {
  projectId: string;
  workshopId?: string;
  content: string;
  recordDate: string;
  source: string;
}

export interface CreateRecordResponse {
  id: string;
  recordType: string;
  recordTypeName: string;
  typeConfidence: number;
  status: string;
  completeness: number;
  missingFields: RecordField[];
}

export interface CaptureWithFileResponse {
  recordId: string;
  taskId: string;
}

export interface CaptureResult {
  status: 'running' | 'success' | 'failed';
  recordId?: string;
  recordType?: string;
  recordTypeName?: string;
  typeConfidence?: number;
  content?: string;
  missingFields?: RecordField[];
  completeness?: number;
  message?: string;
}

// ===================== 实体管理 =====================

export interface EntityListItem {
  id: string;
  code: string | null;
  name: string;
  entityType: string;
  model?: string;
  workshopName?: string;
  aliasCount: number;
  mergeStatus: string;
}

export interface EntityListResponse extends PagedResponse<EntityListItem> {}

export interface EntityAliasItem {
  id: string;
  aliasName?: string | null;
  aliasCode?: string | null;
  sourceType: string;
  isPrimary: boolean;
  status: string;
}

export interface EntityRelationshipItem {
  id: string;
  relationshipType: string;
  targetEntity: {
    id: string;
    name: string;
    code: string | null;
    entityType: string;
  };
  direction: 'out' | 'in';
}

export interface EntityConflictItem {
  id: string;
  fieldName: string;
  status: string;
}

export interface EntityDetail {
  id: string;
  projectId: string;
  code: string | null;
  name: string;
  entityType: string;
  properties: {
    model?: string;
    spec?: string;
    material?: string;
    quantity?: string;
  };
  workshop?: { id: string; name: string };
  mergeStatus: string;
  aliases: EntityAliasItem[];
  relationships: EntityRelationshipItem[];
  conflicts: EntityConflictItem[];
}

export interface AddAliasRequest {
  aliasName?: string;
  aliasCode?: string;
  sourceType: 'manual';
}

export interface AddAliasResponse {
  id: string;
}

// ===================== 实体归并待确认 =====================

export interface MergeQueueCandidate {
  id: string;
  name: string;
  code: string | null;
  model?: string;
  sourceType: string;
  workshopName?: string;
}

export interface MergeQueueItem {
  id: string;
  matchReason: string;
  matchScore: number;
  entityA: MergeQueueCandidate;
  entityB: MergeQueueCandidate;
  createdAt: string;
}

export interface MergeQueueListResponse extends PagedResponse<MergeQueueItem> {}

export type MergeDecision =
  | 'confirmed_merge'
  | 'confirmed_separate'
  | 'ignored';

export interface MergeDecisionRequest {
  decision: MergeDecision;
}

export interface MergeDecisionResponse {
  id: string;
  status: string;
  approvalRequestId?: string;
  message?: string;
}

export interface BatchMergeDecisionRequest {
  ids: string[];
  decision: MergeDecision;
}

export interface BatchMergeDecisionResponse {
  processed: number;
  approvalRequestIds: string[];
}

export interface ConflictListItem {
  id: string;
  entityId: string | null;
  entityName: string;
  entityCode: string;
  fieldName: string;
  valueA: string | null;
  valueB: string | null;
  sourceA: string | null;
  sourceB: string | null;
}

export interface ConflictListResponse extends PagedResponse<ConflictListItem> {}

export interface ResolveConflictRequest {
  resolution: 'resolved_a' | 'resolved_b' | 'resolved_manual';
  resolvedValue?: string;
}

export interface ResolveConflictResponse {
  id: string;
  status: string;
  resolvedValue: string;
  approvalRequestId?: string;
  message?: string;
}

export interface PendingCounts {
  mergeQueueCount: number;
  conflictCount: number;
  classifyCount: number;
  approvalCount: number;
}

/* ==================== 角色与权限（v3.2） ==================== */

export const ROLE = {
  SUPER_ADMIN: 'super_admin',
  ADMIN: 'admin',
  MEMBER: 'member',
} as const;
export type Role = (typeof ROLE)[keyof typeof ROLE];

/* ==================== 审批（v3.2） ==================== */

export const APPROVAL_REQUEST_TYPE = {
  DELETE_FILE: 'delete_file',
  DELETE_RECORD: 'delete_record',
  DELETE_ENTITY: 'delete_entity',
  MERGE_ENTITY: 'merge_entity',
  RESOLVE_CONFLICT: 'resolve_conflict',
  EXPORT_DB: 'export_db',
  BACKUP: 'backup',
  OTHER: 'other',
} as const;
export type ApprovalRequestType =
  (typeof APPROVAL_REQUEST_TYPE)[keyof typeof APPROVAL_REQUEST_TYPE];

export const APPROVAL_REQUEST_TYPE_LABELS: Record<string, string> = {
  [APPROVAL_REQUEST_TYPE.DELETE_FILE]: '删除文件',
  [APPROVAL_REQUEST_TYPE.DELETE_RECORD]: '删除记录',
  [APPROVAL_REQUEST_TYPE.DELETE_ENTITY]: '删除实体',
  [APPROVAL_REQUEST_TYPE.MERGE_ENTITY]: '实体归并',
  [APPROVAL_REQUEST_TYPE.RESOLVE_CONFLICT]: '冲突解决',
  [APPROVAL_REQUEST_TYPE.EXPORT_DB]: '导出数据库',
  [APPROVAL_REQUEST_TYPE.BACKUP]: '备份恢复',
  [APPROVAL_REQUEST_TYPE.OTHER]: '其他',
};

export const APPROVAL_STATUS = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  EXECUTED: 'executed',
  CANCELLED: 'cancelled',
} as const;
export type ApprovalStatus = (typeof APPROVAL_STATUS)[keyof typeof APPROVAL_STATUS];

export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  [APPROVAL_STATUS.PENDING]: '待审批',
  [APPROVAL_STATUS.APPROVED]: '已批准',
  [APPROVAL_STATUS.REJECTED]: '已驳回',
  [APPROVAL_STATUS.EXECUTED]: '已执行',
  [APPROVAL_STATUS.CANCELLED]: '已取消',
};

export interface ApprovalListItem {
  id: string;
  requestType: string;
  summary: string;
  payload: Record<string, unknown>;
  requesterName: string;
  status: string;
  createdAt: string;
  approverName?: string;
  rejectReason?: string;
}

export interface ApprovalListResponse extends PagedResponse<ApprovalListItem> {}

export interface ApproveApprovalResponse {
  id: string;
  status: 'executed';
  executed: true;
}

export interface RejectApprovalRequest {
  reason?: string;
}

export interface RejectApprovalResponse {
  id: string;
  status: 'rejected';
}

export interface ApprovalInitiatedResponse {
  approvalRequestId: string;
  status: 'pending';
  message: string;
}

export interface DeleteViaApprovalResponse {
  approvalRequestId: string;
  status: 'pending' | 'executed';
  message: string;
}

