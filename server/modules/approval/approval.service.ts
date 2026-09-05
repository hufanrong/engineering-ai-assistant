import {
  BadRequestException,
  ConflictException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import {
  AuthNPaasService,
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, count, desc, eq, or } from 'drizzle-orm';

import {
  approvalRequest,
  backgroundTask,
  entity,
  entityAlias,
  entityMergeQueue,
  entityRelationship,
  fileWorkshop,
  projectFile,
  siteRecord,
  versionConflict,
} from '@server/database/schema';
import type {
  ApprovalListItem,
  ApprovalListResponse,
  ApproveApprovalResponse,
  RejectApprovalResponse,
} from '@shared/api.interface';
import {
  isRecordValue,
  readEntityProperties,
} from '../entity/entity-property.util';

const APPROVAL_RESOLVABLE_PROPERTY_FIELDS: readonly string[] = [
  'model',
  'spec',
  'material',
  'quantity',
];

export interface CreateApprovalParams {
  projectId: string;
  requestType: string;
  targetId: string;
  payload: Record<string, unknown>;
  summary: string;
  requesterId: string;
}

export interface ListApprovalFilters {
  status?: string;
  requestType?: string;
  offset: number;
  limit: number;
}

type ApprovalRequestRow = typeof approvalRequest.$inferSelect;

function pickI18nText(name: { zh_cn?: string; en_us?: string } | undefined): string {
  return name?.zh_cn || name?.en_us || '';
}

function readPayloadString(payload: unknown, key: string): string {
  if (isRecordValue(payload)) {
    const value = payload[key];
    if (typeof value === 'string' && value.length > 0) {
      return value;
    }
  }
  return '';
}

@Injectable()
export class ApprovalService {
  private readonly logger = new Logger(ApprovalService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly authNPaasService: AuthNPaasService,
  ) {}

  async createApprovalRequest(params: CreateApprovalParams): Promise<string> {
    const inserted = await this.db
      .insert(approvalRequest)
      .values({
        projectId: params.projectId,
        requestType: params.requestType,
        targetId: params.targetId,
        payload: params.payload,
        summary: params.summary,
        requesterId: params.requesterId,
        status: 'pending',
      })
      .returning({ id: approvalRequest.id });
    this.logger.log(
      `createApprovalRequest type=${params.requestType} id=${inserted[0].id}`,
    );
    return inserted[0].id;
  }

  async listApprovals(
    projectId: string,
    filters: ListApprovalFilters,
  ): Promise<ApprovalListResponse> {
    const conditions = [eq(approvalRequest.projectId, projectId)];
    if (filters.status) {
      conditions.push(eq(approvalRequest.status, filters.status));
    }
    if (filters.requestType) {
      conditions.push(eq(approvalRequest.requestType, filters.requestType));
    }
    const where = and(...conditions);

    const rows = await this.db
      .select({
        id: approvalRequest.id,
        requestType: approvalRequest.requestType,
        summary: approvalRequest.summary,
        payload: approvalRequest.payload,
        requesterId: approvalRequest.requesterId,
        status: approvalRequest.status,
        createdAt: approvalRequest.createdAt,
        approverId: approvalRequest.approverId,
        rejectReason: approvalRequest.rejectReason,
      })
      .from(approvalRequest)
      .where(where)
      .orderBy(desc(approvalRequest.createdAt))
      .limit(filters.limit)
      .offset(filters.offset);

    const totalRows = await this.db
      .select({ total: count() })
      .from(approvalRequest)
      .where(where);
    const total = Number(totalRows[0]?.total ?? 0);

    const userIds = [
      ...new Set([
        ...rows.map((row) => row.requesterId),
        ...rows
          .map((row) => row.approverId)
          .filter((id): id is string => Boolean(id)),
      ]),
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

    const items: ApprovalListItem[] = rows.map((row) => ({
      id: row.id,
      requestType: row.requestType,
      summary: row.summary ?? '',
      payload: isRecordValue(row.payload) ? row.payload : {},
      requesterName: userNameMap.get(row.requesterId) ?? '',
      status: row.status,
      createdAt: row.createdAt.toISOString(),
      approverName: row.approverId
        ? userNameMap.get(row.approverId) ?? ''
        : undefined,
      rejectReason: row.rejectReason ?? undefined,
    }));
    return { items, total };
  }

  async approve(id: string, approverId: string): Promise<ApproveApprovalResponse> {
    const rows = await this.db
      .select()
      .from(approvalRequest)
      .where(eq(approvalRequest.id, id))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('审批请求不存在');
    }
    const request = rows[0];
    if (request.status !== 'pending') {
      throw new ConflictException('审批请求已处理，无法重复审批');
    }

    await this.executeByRequest(request);

    const updated = await this.db
      .update(approvalRequest)
      .set({
        status: 'executed',
        approverId,
        updatedAt: new Date(),
        updatedBy: approverId,
      })
      .where(and(eq(approvalRequest.id, id), eq(approvalRequest.status, 'pending')))
      .returning({ id: approvalRequest.id });
    if (updated.length === 0) {
      throw new ConflictException('审批请求已处理，无法重复审批');
    }
    return { id, status: 'executed', executed: true };
  }

  async reject(
    id: string,
    approverId: string,
    reason?: string,
  ): Promise<RejectApprovalResponse> {
    const rows = await this.db
      .select({ id: approvalRequest.id, status: approvalRequest.status })
      .from(approvalRequest)
      .where(eq(approvalRequest.id, id))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('审批请求不存在');
    }
    if (rows[0].status !== 'pending') {
      throw new ConflictException('审批请求已处理，无法重复审批');
    }

    const updated = await this.db
      .update(approvalRequest)
      .set({
        status: 'rejected',
        approverId,
        rejectReason: reason ?? null,
        updatedAt: new Date(),
        updatedBy: approverId,
      })
      .where(and(eq(approvalRequest.id, id), eq(approvalRequest.status, 'pending')))
      .returning({ id: approvalRequest.id });
    if (updated.length === 0) {
      throw new ConflictException('审批请求已处理，无法重复审批');
    }
    return { id, status: 'rejected' };
  }

  private async executeByRequest(request: ApprovalRequestRow): Promise<void> {
    switch (request.requestType) {
      case 'delete_file': {
        const fileId = readPayloadString(request.payload, 'fileId');
        if (!fileId) {
          throw new BadRequestException('审批快照缺少 fileId');
        }
        await this.db.delete(fileWorkshop).where(eq(fileWorkshop.fileId, fileId));
        await this.db.delete(backgroundTask).where(eq(backgroundTask.fileId, fileId));
        const deleted = await this.db
          .delete(projectFile)
          .where(eq(projectFile.id, fileId))
          .returning({ id: projectFile.id });
        if (deleted.length === 0) {
          throw new NotFoundException('文件不存在或已删除');
        }
        break;
      }
      case 'delete_record': {
        const recordId = readPayloadString(request.payload, 'recordId');
        if (!recordId) {
          throw new BadRequestException('审批快照缺少 recordId');
        }
        await this.db.delete(backgroundTask).where(eq(backgroundTask.recordId, recordId));
        const deleted = await this.db
          .delete(siteRecord)
          .where(eq(siteRecord.id, recordId))
          .returning({ id: siteRecord.id });
        if (deleted.length === 0) {
          throw new NotFoundException('记录不存在或已删除');
        }
        break;
      }
      case 'delete_entity': {
        const entityId = readPayloadString(request.payload, 'entityId');
        if (!entityId) {
          throw new BadRequestException('审批快照缺少 entityId');
        }
        await this.executeDeleteEntity(entityId);
        break;
      }
      case 'merge_entity': {
        const queueId = readPayloadString(request.payload, 'queueId');
        const entityAId = readPayloadString(request.payload, 'entityAId');
        const entityBId = readPayloadString(request.payload, 'entityBId');
        if (!queueId || !entityAId || !entityBId) {
          throw new BadRequestException('审批快照缺少实体引用，无法执行合并');
        }
        await this.db.transaction(async (tx) => {
          await tx
            .update(entityAlias)
            .set({ entityId: entityAId, updatedAt: new Date() })
            .where(eq(entityAlias.entityId, entityBId));
          await tx
            .update(entityRelationship)
            .set({ sourceEntityId: entityAId, updatedAt: new Date() })
            .where(eq(entityRelationship.sourceEntityId, entityBId));
          await tx
            .update(entityRelationship)
            .set({ targetEntityId: entityAId, updatedAt: new Date() })
            .where(eq(entityRelationship.targetEntityId, entityBId));
          await tx.delete(entityRelationship).where(
            and(
              eq(entityRelationship.sourceEntityId, entityAId),
              eq(entityRelationship.targetEntityId, entityAId),
            ),
          );
          const deleted = await tx
            .delete(entity)
            .where(eq(entity.id, entityBId))
            .returning({ id: entity.id });
          if (deleted.length === 0) {
            throw new NotFoundException('待合并实体不存在');
          }
          await tx
            .update(entity)
            .set({ mergeStatus: 'merged', updatedAt: new Date() })
            .where(eq(entity.id, entityAId));
          await tx
            .update(entityMergeQueue)
            .set({ status: 'confirmed_merge', updatedAt: new Date() })
            .where(eq(entityMergeQueue.id, queueId));
        });
        break;
      }
      case 'resolve_conflict': {
        const conflictId = readPayloadString(request.payload, 'conflictId');
        const resolution = readPayloadString(request.payload, 'resolution');
        const resolvedValue = readPayloadString(request.payload, 'resolvedValue');
        if (!conflictId || !resolution) {
          throw new BadRequestException('审批快照缺少冲突解决参数');
        }
        const conflictRows = await this.db
          .select()
          .from(versionConflict)
          .where(eq(versionConflict.id, conflictId))
          .limit(1);
        if (conflictRows.length === 0) {
          throw new NotFoundException('冲突记录不存在');
        }
        const conflictRow = conflictRows[0];
        const updated = await this.db
          .update(versionConflict)
          .set({ status: resolution, resolvedValue, updatedAt: new Date() })
          .where(eq(versionConflict.id, conflictId))
          .returning({ id: versionConflict.id });
        if (updated.length === 0) {
          throw new NotFoundException('冲突记录不存在');
        }
        if (
          conflictRow.entityId &&
          APPROVAL_RESOLVABLE_PROPERTY_FIELDS.includes(conflictRow.fieldName)
        ) {
          await this.syncEntityProperty(
            conflictRow.entityId,
            conflictRow.fieldName,
            resolvedValue,
          );
        }
        break;
      }
      default:
        throw new BadRequestException(`不支持的审批类型: ${request.requestType}`);
    }
  }

  private async executeDeleteEntity(entityId: string): Promise<void> {
    await this.db.delete(entityAlias).where(eq(entityAlias.entityId, entityId));
    await this.db
      .delete(entityRelationship)
      .where(
        or(
          eq(entityRelationship.sourceEntityId, entityId),
          eq(entityRelationship.targetEntityId, entityId),
        ),
      );
    await this.db
      .delete(entityMergeQueue)
      .where(
        or(
          eq(entityMergeQueue.entityAId, entityId),
          eq(entityMergeQueue.entityBId, entityId),
        ),
      );
    await this.db.delete(versionConflict).where(eq(versionConflict.entityId, entityId));
    const deleted = await this.db
      .delete(entity)
      .where(eq(entity.id, entityId))
      .returning({ id: entity.id });
    if (deleted.length === 0) {
      throw new NotFoundException('实体不存在或已删除');
    }
  }

  private async syncEntityProperty(
    entityId: string,
    fieldName: string,
    resolvedValue: string,
  ): Promise<void> {
    const entityRows = await this.db
      .select({ properties: entity.properties })
      .from(entity)
      .where(eq(entity.id, entityId))
      .limit(1);
    if (entityRows.length === 0) {
      return;
    }
    const props = readEntityProperties(entityRows[0].properties);
    props[fieldName as 'model' | 'spec' | 'material' | 'quantity'] = resolvedValue;
    await this.db
      .update(entity)
      .set({ properties: props, updatedAt: new Date() })
      .where(eq(entity.id, entityId));
  }
}
