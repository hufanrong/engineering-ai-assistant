import { createHash } from 'crypto';

import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
  AuthNPaasService,
  CapabilityService,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, count, desc, eq, ilike, or } from 'drizzle-orm';

import { backgroundTask, project, projectFile, siteRecord, workshop } from '@server/database/schema';
import type {
  CaptureResult,
  CaptureWithFileResponse,
  CreateRecordRequest,
  CreateRecordResponse,
  DeleteViaApprovalResponse,
  RecordDetail,
  RecordField,
  RecordListItem,
  RecordStatus,
  RecordTypeConfigItem,
  RecordTypeConfigResponse,
  SupplementRequest,
  SupplementResponse,
  UpdateRecordRequest,
  UpdateRecordResponse,
} from '@shared/api.interface';
import { RECORD_STATUS } from '@shared/api.interface';

import { CompletenessService } from './completeness.service';
import { TypeRecognitionService } from './type-recognition.service';
import { ApprovalService } from '../approval/approval.service';
import { isSuperAdmin, type UserContextWithRoles } from '../approval/user-context';

const VOICE_PLUGIN_ID = 'mobile_voice_transcription_1';
const VOICE_ACTION_KEY = 'speechToText';
const PHOTO_PLUGIN_ID = 'site_photo_structured_extraction_1';
const PHOTO_ACTION_KEY = 'imageToJson';

export interface ListRecordsParams {
  projectId?: string;
  recordType?: string;
  status?: string;
  keyword?: string;
  creatorUserId?: string;
  offset: number;
  limit: number;
}

export interface CaptureWithFileDto {
  fileUrl: string;
  projectId: string;
  workshopId?: string;
  recordDate: string;
  source: string;
}

interface TaskRow {
  id: string;
  projectId: string;
  fileId: string | null;
  recordId: string | null;
  taskType: string;
  status: string;
  message: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object';
}

function readStringField(output: unknown, keys: string[]): string {
  if (!isRecord(output)) {
    return '';
  }
  for (const key of keys) {
    const value = output[key];
    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }
  return '';
}

function pickI18nText(name: { zh_cn?: string; en_us?: string } | undefined): string {
  return name?.zh_cn || name?.en_us || '';
}

@Injectable()
export class RecordService {
  private readonly logger = new Logger(RecordService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly authNPaasService: AuthNPaasService,
    private readonly capabilityService: CapabilityService,
    private readonly typeRecognitionService: TypeRecognitionService,
    private readonly completenessService: CompletenessService,
    private readonly approvalService: ApprovalService,
  ) {}

  getModuleStatus(): { module: string; status: string } {
    return { module: 'record', status: 'ok' };
  }

  async listRecordTypeConfigs(): Promise<RecordTypeConfigResponse> {
    const configs = await this.typeRecognitionService.getConfigs();
    const items: RecordTypeConfigItem[] = configs.map((c) => ({
      recordType: c.recordType,
      displayName: c.displayName,
      category: c.category,
      requiredFields: c.requiredFields ?? [],
      keywords: c.keywords ?? [],
    }));
    return { items };
  }

  async listRecords(params: ListRecordsParams): Promise<{ items: RecordListItem[]; total: number }> {
    const conditions = [];
    if (params.projectId) {
      conditions.push(eq(siteRecord.projectId, params.projectId));
    }
    if (params.recordType) {
      conditions.push(eq(siteRecord.recordType, params.recordType));
    }
    if (params.status) {
      conditions.push(eq(siteRecord.status, params.status));
    }
    if (params.keyword) {
      conditions.push(
        or(ilike(siteRecord.title, `%${params.keyword}%`), ilike(siteRecord.content, `%${params.keyword}%`)),
      );
    }
    if (params.creatorUserId) {
      conditions.push(eq(siteRecord.createdBy, params.creatorUserId));
    }
    const where = conditions.length > 0 ? and(...conditions) : undefined;

    const rows = await this.db
      .select({
        id: siteRecord.id,
        title: siteRecord.title,
        recordType: siteRecord.recordType,
        projectId: siteRecord.projectId,
        projectName: project.name,
        workshopName: workshop.name,
        recordDate: siteRecord.recordDate,
        status: siteRecord.status,
        completeness: siteRecord.completeness,
        createdBy: siteRecord.createdBy,
        createdAt: siteRecord.createdAt,
      })
      .from(siteRecord)
      .innerJoin(project, eq(siteRecord.projectId, project.id))
      .leftJoin(workshop, eq(siteRecord.workshopId, workshop.id))
      .where(where)
      .orderBy(desc(siteRecord.createdAt))
      .limit(params.limit)
      .offset(params.offset);

    const totalRows = await this.db
      .select({ total: count() })
      .from(siteRecord)
      .where(where);
    const total = Number(totalRows[0]?.total ?? 0);

    const configs = await this.typeRecognitionService.getConfigs();
    const typeNameMap = new Map(configs.map((c) => [c.recordType, c.displayName]));

    const userIds = [
      ...new Set(rows.map((r) => r.createdBy).filter((id): id is string => Boolean(id))),
    ];
    const userNameMap = new Map<string, string>();
    if (userIds.length > 0) {
      const users = await this.authNPaasService.listUsersByIds(userIds);
      for (const user of users) {
        if (user) {
          userNameMap.set(user.miaodaUserID, pickI18nText(user.name));
        }
      }
    }

    const items: RecordListItem[] = rows.map((row) => ({
      id: row.id,
      title: row.title ?? '未命名记录',
      recordType: row.recordType,
      recordTypeName: typeNameMap.get(row.recordType) ?? row.recordType,
      projectId: row.projectId,
      projectName: row.projectName,
      workshopName: row.workshopName ?? undefined,
      recordDate: row.recordDate ?? undefined,
      status: row.status,
      completeness: row.completeness,
      creatorName: (row.createdBy && userNameMap.get(row.createdBy)) || '系统',
      createdAt: row.createdAt.toISOString(),
    }));
    return { items, total };
  }

  async deleteRecordWithApproval(
    id: string,
    userContext: UserContextWithRoles,
  ): Promise<DeleteViaApprovalResponse> {
    const rows = await this.db
      .select({
        id: siteRecord.id,
        title: siteRecord.title,
        projectId: siteRecord.projectId,
      })
      .from(siteRecord)
      .where(eq(siteRecord.id, id))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('记录不存在');
    }
    const recordRow = rows[0];
    const title = recordRow.title ?? '未命名记录';

    if (isSuperAdmin(userContext)) {
      await this.db.delete(backgroundTask).where(eq(backgroundTask.recordId, id));
      await this.db.delete(siteRecord).where(eq(siteRecord.id, id));
      return { approvalRequestId: '', status: 'executed', message: '记录已删除' };
    }

    const approvalRequestId = await this.approvalService.createApprovalRequest({
      projectId: recordRow.projectId,
      requestType: 'delete_record',
      targetId: id,
      payload: {
        recordId: id,
        title,
        projectId: recordRow.projectId,
      },
      summary: `删除记录：${title}`,
      requesterId: userContext.userId,
    });
    return {
      approvalRequestId,
      status: 'pending',
      message: '已提交审批，等待超级管理员审批',
    };
  }

  async getRecordDetail(id: string): Promise<RecordDetail> {
    const rows = await this.db.select().from(siteRecord).where(eq(siteRecord.id, id));
    if (rows.length === 0) {
      throw new NotFoundException('记录不存在');
    }
    const row = rows[0];

    const config = await this.typeRecognitionService.getConfigByType(row.recordType);
    let workshopInfo: { id: string; name: string } | undefined;
    if (row.workshopId) {
      const workshopRows = await this.db
        .select({ id: workshop.id, name: workshop.name })
        .from(workshop)
        .where(eq(workshop.id, row.workshopId));
      workshopInfo = workshopRows[0] ?? undefined;
    }

    const attachments: Array<{ id: string; filename: string; fileUrl: string }> = [];
    if (row.attachedFileId) {
      const fileRows = await this.db
        .select({ id: projectFile.id, filename: projectFile.filename, fileUrl: projectFile.fileUrl })
        .from(projectFile)
        .where(eq(projectFile.id, row.attachedFileId));
      for (const f of fileRows) {
        attachments.push({ id: f.id, filename: f.filename, fileUrl: f.fileUrl });
      }
    }

    const missingFields: RecordField[] = Array.isArray(row.missingFields)
      ? (row.missingFields as RecordField[])
      : [];

    return {
      id: row.id,
      projectId: row.projectId,
      title: row.title ?? '未命名记录',
      recordType: row.recordType,
      recordTypeName: config?.displayName ?? row.recordType,
      content: row.content ?? '',
      recordDate: row.recordDate ?? undefined,
      location: row.location ?? undefined,
      status: row.status,
      completeness: row.completeness,
      missingFields,
      typeConfidence: row.typeConfidence,
      typeModified: row.typeModified,
      workshop: workshopInfo,
      relatedEntities: [],
      attachments,
    };
  }

  async updateRecord(
    id: string,
    dto: UpdateRecordRequest,
    userId: string,
  ): Promise<UpdateRecordResponse> {
    const rows = await this.db.select().from(siteRecord).where(eq(siteRecord.id, id));
    if (rows.length === 0) {
      throw new NotFoundException('记录不存在');
    }
    const current = rows[0];

    const patch: Partial<typeof siteRecord.$inferInsert> = {};
    if (dto.title !== undefined) patch.title = dto.title;
    if (dto.content !== undefined) patch.content = dto.content;
    if (dto.location !== undefined) patch.location = dto.location;
    if (dto.recordDate !== undefined) patch.recordDate = dto.recordDate;

    const typeChanged = dto.recordType !== undefined && dto.recordType !== current.recordType;
    let nextRecordType = current.recordType;
    let nextStatus = current.status;
    let nextCompleteness = current.completeness;

    if (typeChanged && dto.recordType) {
      nextRecordType = dto.recordType;
      patch.recordType = dto.recordType;
      patch.typeModified = true;
      patch.typeConfidence = 1;
    }

    if (typeChanged || dto.content !== undefined) {
      const nextContent = dto.content !== undefined ? dto.content : current.content ?? '';
      const result = await this.completenessService.check(nextRecordType, nextContent);
      nextCompleteness = result.completeness;
      patch.completeness = result.completeness;
      patch.missingFields = result.missingFields;
      if (typeChanged) {
        nextStatus =
          result.completeness >= 100 ? RECORD_STATUS.COMPLETE : RECORD_STATUS.PENDING_SUPPLEMENT;
      } else if (current.status !== RECORD_STATUS.PENDING_CLASSIFY) {
        nextStatus =
          result.completeness >= 100 ? RECORD_STATUS.COMPLETE : RECORD_STATUS.PENDING_SUPPLEMENT;
      }
      patch.status = nextStatus;
    }

    if (Object.keys(patch).length === 0) {
      throw new NotFoundException('未提供可更新字段');
    }
    patch.updatedAt = new Date();
    patch.updatedBy = userId;

    const updated = await this.db
      .update(siteRecord)
      .set(patch)
      .where(eq(siteRecord.id, id))
      .returning({ id: siteRecord.id });
    if (updated.length === 0) {
      throw new NotFoundException('记录不存在');
    }

    return {
      id,
      recordType: nextRecordType,
      status: nextStatus,
      completeness: nextCompleteness,
    };
  }

  async supplementRecord(
    id: string,
    dto: SupplementRequest,
    userId: string,
  ): Promise<SupplementResponse> {
    const rows = await this.db.select().from(siteRecord).where(eq(siteRecord.id, id));
    if (rows.length === 0) {
      throw new NotFoundException('记录不存在');
    }
    const current = rows[0];

    const config = await this.typeRecognitionService.getConfigByType(current.recordType);
    const fieldMap = new Map<string, string>();
    for (const field of config?.requiredFields ?? []) {
      fieldMap.set(field.key, field.label);
    }

    const additions: string[] = [];
    for (const item of dto.supplements) {
      if (!item || typeof item.value !== 'string' || item.value.trim().length === 0) {
        continue;
      }
      const label = fieldMap.get(item.key) ?? item.key;
      additions.push(`\n${label}：${item.value.trim()}`);
    }
    if (additions.length === 0) {
      throw new NotFoundException('未提供有效补充内容');
    }

    const nextContent = `${current.content ?? ''}${additions.join('')}`;
    const result = await this.completenessService.check(current.recordType, nextContent);
    const nextStatus =
      result.completeness >= 100 ? RECORD_STATUS.COMPLETE : RECORD_STATUS.PENDING_SUPPLEMENT;

    const updated = await this.db
      .update(siteRecord)
      .set({
        content: nextContent,
        completeness: result.completeness,
        missingFields: result.missingFields,
        status: nextStatus,
        updatedAt: new Date(),
        updatedBy: userId,
      })
      .where(eq(siteRecord.id, id))
      .returning({ id: siteRecord.id });
    if (updated.length === 0) {
      throw new NotFoundException('记录不存在');
    }

    return {
      id,
      status: nextStatus,
      completeness: result.completeness,
      missingFields: result.missingFields,
    };
  }

  async createRecord(dto: CreateRecordRequest, userId: string): Promise<CreateRecordResponse> {
    const recognition = await this.typeRecognitionService.recognize(dto.content);
    const completenessResult = await this.completenessService.check(recognition.recordType, dto.content);

    let status: RecordStatus;
    if (recognition.highConfidence) {
      status =
        completenessResult.completeness >= 100
          ? RECORD_STATUS.COMPLETE
          : RECORD_STATUS.PENDING_SUPPLEMENT;
    } else {
      status = RECORD_STATUS.PENDING_CLASSIFY;
    }

    const title = dto.content.trim().slice(0, 50);

    const inserted = await this.db
      .insert(siteRecord)
      .values({
        projectId: dto.projectId,
        workshopId: dto.workshopId ?? null,
        recordType: recognition.recordType,
        title,
        content: dto.content,
        recordDate: dto.recordDate,
        status,
        completeness: completenessResult.completeness,
        missingFields: completenessResult.missingFields,
        typeConfidence: recognition.confidence,
        typeModified: false,
      })
      .returning({ id: siteRecord.id });

    const config = await this.typeRecognitionService.getConfigByType(recognition.recordType);
    return {
      id: inserted[0].id,
      recordType: recognition.recordType,
      recordTypeName: config?.displayName ?? recognition.recordType,
      typeConfidence: recognition.confidence,
      status,
      completeness: completenessResult.completeness,
      missingFields: completenessResult.missingFields,
    };
  }

  async captureWithFile(dto: CaptureWithFileDto, userId: string): Promise<CaptureWithFileResponse> {
    const recordInserted = await this.db
      .insert(siteRecord)
      .values({
        projectId: dto.projectId,
        workshopId: dto.workshopId ?? null,
        recordType: 'other',
        title: '采集识别中',
        content: '',
        recordDate: dto.recordDate,
        status: RECORD_STATUS.PENDING_CLASSIFY,
        completeness: 0,
        typeConfidence: 0,
      })
      .returning({ id: siteRecord.id });
    const recordId = recordInserted[0].id;

    const filename = decodeURIComponent(dto.fileUrl.split('/').pop() ?? 'capture-file');
    const sha256 = createHash('sha256').update(`${dto.fileUrl}:${recordId}`).digest('hex');
    const fileInserted = await this.db
      .insert(projectFile)
      .values({
        projectId: dto.projectId,
        filename,
        fileUrl: dto.fileUrl,
        fileType: dto.source === 'mobile_photo' ? 'image' : 'audio',
        fileSize: 0,
        sha256,
        source: dto.source,
        recordId,
      })
      .returning({ id: projectFile.id });
    const fileId = fileInserted[0].id;

    const taskType = dto.source === 'mobile_photo' ? 'image_extract' : 'audio_transcribe';
    const taskInserted = await this.db
      .insert(backgroundTask)
      .values({
        projectId: dto.projectId,
        fileId,
        recordId,
        taskType,
        status: 'pending',
      })
      .returning({ id: backgroundTask.id });
    const taskId = taskInserted[0].id;

    await this.db
      .update(siteRecord)
      .set({ attachedFileId: fileId, updatedAt: new Date(), updatedBy: userId })
      .where(eq(siteRecord.id, recordId));

    this.processCapture(taskId, userId).catch((error: unknown) => {
      this.logger.error(
        `processCapture unexpected failure: ${error instanceof Error ? error.message : 'unknown'}`,
      );
    });

    return { recordId, taskId };
  }

  async getCaptureResult(taskId: string): Promise<CaptureResult> {
    const taskRows = await this.db.select().from(backgroundTask).where(eq(backgroundTask.id, taskId));
    if (taskRows.length === 0) {
      throw new NotFoundException('任务不存在');
    }
    const task = taskRows[0];

    if (task.status === 'pending' || task.status === 'running') {
      return { status: 'running' };
    }
    if (task.status === 'failed') {
      return { status: 'failed', message: task.message ?? '处理失败' };
    }

    if (!task.recordId) {
      return { status: 'failed', message: '任务未关联记录' };
    }
    const detail = await this.getRecordDetail(task.recordId);
    return {
      status: 'success',
      recordId: detail.id,
      recordType: detail.recordType,
      recordTypeName: detail.recordTypeName,
      typeConfidence: detail.typeConfidence,
      content: detail.content,
      missingFields: detail.missingFields,
      completeness: detail.completeness,
    };
  }

  private async processCapture(taskId: string, userId: string): Promise<void> {
    const taskRows = await this.db.select().from(backgroundTask).where(eq(backgroundTask.id, taskId));
    if (taskRows.length === 0) {
      return;
    }
    const task = taskRows[0];

    try {
      await this.db
        .update(backgroundTask)
        .set({ status: 'running', progress: 10, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));

      const fileUrl = await this.getTaskFileUrl(task);
      let content = '';
      let extractedTitle = '';
      let location = '';

      if (task.taskType === 'image_extract') {
        const output = await this.capabilityService
          .load(PHOTO_PLUGIN_ID)
          .call(PHOTO_ACTION_KEY, { imageUrl: [fileUrl] });
        const extractedContent = readStringField(output, ['content']);
        const extractedLocation = readStringField(output, ['location']);
        const extraInfo = readStringField(output, ['extraInfo']);
        extractedTitle = readStringField(output, ['title']);
        const parts: string[] = [];
        if (extractedContent) parts.push(extractedContent);
        if (extractedLocation) parts.push(`位置：${extractedLocation}`);
        if (extraInfo) parts.push(`补充信息：${extraInfo}`);
        content = parts.join('\n');
        location = extractedLocation;
      } else {
        const output = await this.capabilityService
          .load(VOICE_PLUGIN_ID)
          .call(VOICE_ACTION_KEY, { fileUrl: [fileUrl] });
        content = readStringField(output, ['text']);
      }

      if (!content && !extractedTitle) {
        throw new Error('插件未返回有效内容');
      }

      const recognition = await this.typeRecognitionService.recognize(content);
      const completenessResult = await this.completenessService.check(recognition.recordType, content);
      let status: RecordStatus;
      if (recognition.highConfidence) {
        status =
          completenessResult.completeness >= 100
            ? RECORD_STATUS.COMPLETE
            : RECORD_STATUS.PENDING_SUPPLEMENT;
      } else {
        status = RECORD_STATUS.PENDING_CLASSIFY;
      }
      const title = (extractedTitle || content).trim().slice(0, 50);

      if (task.recordId) {
        const updated = await this.db
          .update(siteRecord)
          .set({
            title,
            content,
            recordType: recognition.recordType,
            status,
            completeness: completenessResult.completeness,
            missingFields: completenessResult.missingFields,
            typeConfidence: recognition.confidence,
            ...(location ? { location } : {}),
            updatedAt: new Date(),
            updatedBy: userId,
          })
          .where(eq(siteRecord.id, task.recordId))
          .returning({ id: siteRecord.id });
        if (updated.length === 0) {
          throw new Error('关联记录不存在');
        }
      }

      await this.db
        .update(backgroundTask)
        .set({ status: 'success', progress: 100, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));
    } catch (error) {
      const message = error instanceof Error ? error.message : '未知错误';
      const pluginInstanceId =
        task.taskType === 'image_extract' ? PHOTO_PLUGIN_ID : VOICE_PLUGIN_ID;
      const actionKey = task.taskType === 'image_extract' ? PHOTO_ACTION_KEY : VOICE_ACTION_KEY;
      this.logger.error(
        `processCapture failed: ${JSON.stringify({
          taskId,
          pluginInstanceId,
          actionKey,
          outputMode: 'unary',
          error: message,
        })}`,
      );
      await this.db
        .update(backgroundTask)
        .set({ status: 'failed', message, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));
    }
  }

  private async getTaskFileUrl(task: TaskRow): Promise<string> {
    if (!task.fileId) {
      throw new Error('任务未关联文件');
    }
    const fileRows = await this.db
      .select({ fileUrl: projectFile.fileUrl })
      .from(projectFile)
      .where(eq(projectFile.id, task.fileId));
    if (fileRows.length === 0) {
      throw new Error('关联文件不存在');
    }
    return fileRows[0].fileUrl;
  }
}
