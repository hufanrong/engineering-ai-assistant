import {
  BadRequestException,
  Inject,
  Injectable,
  Logger,
  NotFoundException,
} from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, eq, or } from 'drizzle-orm';

import type {
  AddAliasRequest,
  AddAliasResponse,
  BatchMergeDecisionResponse,
  DeleteViaApprovalResponse,
  MergeDecision,
  MergeDecisionResponse,
  ResolveConflictRequest,
  ResolveConflictResponse,
} from '@shared/api.interface';
import { ApprovalService } from '../approval/approval.service';
import {
  isSuperAdmin,
  type UserContextWithRoles,
} from '../approval/user-context';
import {
  entity,
  entityAlias,
  entityMergeQueue,
  entityRelationship,
  versionConflict,
} from '@server/database/schema';
import { readEntityProperties } from './entity-property.util';

const RESOLVABLE_PROPERTY_FIELDS: readonly string[] = [
  'model',
  'spec',
  'material',
  'quantity',
];

@Injectable()
export class EntityDecisionService {
  private readonly logger = new Logger(EntityDecisionService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly approvalService: ApprovalService,
  ) {}

  async addAlias(entityId: string, dto: AddAliasRequest): Promise<AddAliasResponse> {
    const entityRows = await this.db
      .select({ id: entity.id, projectId: entity.projectId })
      .from(entity)
      .where(eq(entity.id, entityId))
      .limit(1);
    if (entityRows.length === 0) {
      throw new NotFoundException('实体不存在');
    }
    const inserted = await this.db
      .insert(entityAlias)
      .values({
        projectId: entityRows[0].projectId,
        entityId,
        aliasName: dto.aliasName ? dto.aliasName : null,
        aliasCode: dto.aliasCode ? dto.aliasCode : null,
        sourceType: 'manual',
        isPrimary: false,
        status: 'confirmed',
        confidence: 1,
      })
      .returning({ id: entityAlias.id });
    return { id: inserted[0].id };
  }

  async decisionMerge(
    queueId: string,
    decision: MergeDecision,
    userContext: UserContextWithRoles,
  ): Promise<MergeDecisionResponse> {
    const queueRows = await this.db
      .select()
      .from(entityMergeQueue)
      .where(eq(entityMergeQueue.id, queueId))
      .limit(1);
    if (queueRows.length === 0) {
      throw new NotFoundException('归并队列项不存在');
    }
    const queueRow = queueRows[0];
    const aId = queueRow.entityAId;
    const bId = queueRow.entityBId;

    if (decision === 'confirmed_merge') {
      if (!aId || !bId) {
        throw new BadRequestException('队列项缺少实体引用，无法执行合并');
      }
      if (!isSuperAdmin(userContext)) {
        const approvalRequestId = await this.approvalService.createApprovalRequest({
          projectId: queueRow.projectId,
          requestType: 'merge_entity',
          targetId: queueId,
          payload: {
            queueId,
            entityAId: aId,
            entityBId: bId,
            aName: queueRow.aName ?? '',
            bName: queueRow.bName ?? '',
            projectId: queueRow.projectId,
          },
          summary: `实体归并：${queueRow.aName ?? ''} / ${queueRow.bName ?? ''}`,
          requesterId: userContext.userId,
        });
        return {
          id: queueId,
          status: 'pending',
          approvalRequestId,
          message: '已提交审批，等待超级管理员审批',
        };
      }
      await this.db.transaction(async (tx) => {
        await tx
          .update(entityAlias)
          .set({ entityId: aId, updatedAt: new Date() })
          .where(eq(entityAlias.entityId, bId));
        await tx
          .update(entityRelationship)
          .set({ sourceEntityId: aId, updatedAt: new Date() })
          .where(eq(entityRelationship.sourceEntityId, bId));
        await tx
          .update(entityRelationship)
          .set({ targetEntityId: aId, updatedAt: new Date() })
          .where(eq(entityRelationship.targetEntityId, bId));
        await tx
          .delete(entityRelationship)
          .where(
            and(
              eq(entityRelationship.sourceEntityId, aId),
              eq(entityRelationship.targetEntityId, aId),
            ),
          );
        const deleted = await tx
          .delete(entity)
          .where(eq(entity.id, bId))
          .returning({ id: entity.id });
        if (deleted.length === 0) {
          throw new NotFoundException('待合并实体不存在');
        }
        await tx
          .update(entity)
          .set({ mergeStatus: 'merged', updatedAt: new Date() })
          .where(eq(entity.id, aId));
      });
    } else {
      const entityIds: string[] = [];
      if (aId) entityIds.push(aId);
      if (bId) entityIds.push(bId);
      for (const entityId of entityIds) {
        await this.db
          .update(entity)
          .set({ mergeStatus: 'standalone', updatedAt: new Date() })
          .where(eq(entity.id, entityId));
      }
    }

    await this.db
      .update(entityMergeQueue)
      .set({ status: decision, updatedAt: new Date() })
      .where(eq(entityMergeQueue.id, queueId));
    return { id: queueId, status: decision };
  }

  async batchDecision(
    ids: string[],
    decision: MergeDecision,
    userContext: UserContextWithRoles,
  ): Promise<BatchMergeDecisionResponse> {
    let processed = 0;
    const approvalRequestIds: string[] = [];
    for (const queueId of ids) {
      try {
        const result = await this.decisionMerge(queueId, decision, userContext);
        processed += 1;
        approvalRequestIds.push(result.approvalRequestId ?? '');
      } catch (error) {
        this.logger.error(
          `batchDecision single item failed: ${JSON.stringify({
            queueId,
            decision,
            error: error instanceof Error ? error.message : String(error),
          })}`,
        );
      }
    }
    return { processed, approvalRequestIds };
  }

  async deleteEntityWithApproval(
    entityId: string,
    userContext: UserContextWithRoles,
  ): Promise<DeleteViaApprovalResponse> {
    const entityRows = await this.db
      .select({
        id: entity.id,
        name: entity.name,
        code: entity.code,
        projectId: entity.projectId,
      })
      .from(entity)
      .where(eq(entity.id, entityId))
      .limit(1);
    if (entityRows.length === 0) {
      throw new NotFoundException('实体不存在');
    }
    const entityRow = entityRows[0];

    if (isSuperAdmin(userContext)) {
      await this.executeDeleteEntity(entityId);
      return { approvalRequestId: '', status: 'executed', message: '实体已删除' };
    }

    const approvalRequestId = await this.approvalService.createApprovalRequest({
      projectId: entityRow.projectId,
      requestType: 'delete_entity',
      targetId: entityId,
      payload: {
        entityId,
        name: entityRow.name,
        code: entityRow.code ?? '',
        projectId: entityRow.projectId,
      },
      summary: `删除实体：${entityRow.name}`,
      requesterId: userContext.userId,
    });
    return {
      approvalRequestId,
      status: 'pending',
      message: '已提交审批，等待超级管理员审批',
    };
  }

  async resolveConflict(
    conflictId: string,
    dto: ResolveConflictRequest,
    userContext: UserContextWithRoles,
  ): Promise<ResolveConflictResponse> {
    const conflictRows = await this.db
      .select()
      .from(versionConflict)
      .where(eq(versionConflict.id, conflictId))
      .limit(1);
    if (conflictRows.length === 0) {
      throw new NotFoundException('冲突记录不存在');
    }
    const conflictRow = conflictRows[0];

    let resolvedValue = '';
    if (dto.resolution === 'resolved_a') {
      resolvedValue = conflictRow.valueA ?? '';
    } else if (dto.resolution === 'resolved_b') {
      resolvedValue = conflictRow.valueB ?? '';
    } else {
      resolvedValue = dto.resolvedValue ?? '';
    }

    if (!isSuperAdmin(userContext)) {
      const approvalRequestId = await this.approvalService.createApprovalRequest({
        projectId: conflictRow.projectId,
        requestType: 'resolve_conflict',
        targetId: conflictId,
        payload: {
          conflictId,
          resolution: dto.resolution,
          resolvedValue,
          entityId: conflictRow.entityId,
          projectId: conflictRow.projectId,
        },
        summary: `冲突解决：${conflictRow.fieldName}`,
        requesterId: userContext.userId,
      });
      return {
        id: conflictId,
        status: 'pending',
        resolvedValue,
        approvalRequestId,
        message: '已提交审批，等待超级管理员审批',
      };
    }

    const updated = await this.db
      .update(versionConflict)
      .set({ status: dto.resolution, resolvedValue, updatedAt: new Date() })
      .where(eq(versionConflict.id, conflictId))
      .returning({ id: versionConflict.id });
    if (updated.length === 0) {
      throw new NotFoundException('冲突记录不存在');
    }

    if (
      conflictRow.entityId &&
      RESOLVABLE_PROPERTY_FIELDS.includes(conflictRow.fieldName)
    ) {
      await this.syncEntityProperty(conflictRow.entityId, conflictRow.fieldName, resolvedValue);
    }
    return { id: conflictId, status: dto.resolution, resolvedValue };
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
      throw new NotFoundException('实体不存在');
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
