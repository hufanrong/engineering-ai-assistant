import { Inject, Injectable } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, count, desc, eq, inArray } from 'drizzle-orm';

import type {
  ConflictListItem,
  ConflictListResponse,
  MergeQueueCandidate,
  MergeQueueItem,
  MergeQueueListResponse,
  PendingCounts,
} from '@shared/api.interface';
import {
  approvalRequest,
  entity,
  entityAlias,
  entityMergeQueue,
  siteRecord,
  versionConflict,
  workshop,
} from '@server/database/schema';
import { readEntityProperties } from './entity-property.util';

interface QueueRow {
  id: string;
  entityAId: string | null;
  entityBId: string | null;
  aName: string | null;
  aCode: string | null;
  bName: string | null;
  bCode: string | null;
  matchReason: string | null;
  matchScore: number;
  createdAt: Date;
}

interface EntitySnapshotRow {
  id: string;
  name: string;
  code: string | null;
  properties: unknown;
  workshopName: string | null;
}

@Injectable()
export class EntityQueueService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async listMergeQueue(
    projectId: string,
    status: string,
    offset: number,
    limit: number,
  ): Promise<MergeQueueListResponse> {
    const whereClause = and(
      eq(entityMergeQueue.projectId, projectId),
      eq(entityMergeQueue.status, status),
    );
    const rows: QueueRow[] = await this.db
      .select({
        id: entityMergeQueue.id,
        entityAId: entityMergeQueue.entityAId,
        entityBId: entityMergeQueue.entityBId,
        aName: entityMergeQueue.aName,
        aCode: entityMergeQueue.aCode,
        bName: entityMergeQueue.bName,
        bCode: entityMergeQueue.bCode,
        matchReason: entityMergeQueue.matchReason,
        matchScore: entityMergeQueue.matchScore,
        createdAt: entityMergeQueue.createdAt,
      })
      .from(entityMergeQueue)
      .where(whereClause)
      .orderBy(desc(entityMergeQueue.createdAt))
      .limit(limit)
      .offset(offset);

    const totalRows = await this.db
      .select({ total: count() })
      .from(entityMergeQueue)
      .where(whereClause);
    const total = Number(totalRows[0]?.total ?? 0);

    const entityIds: string[] = [];
    for (const row of rows) {
      if (row.entityAId) entityIds.push(row.entityAId);
      if (row.entityBId) entityIds.push(row.entityBId);
    }
    const entityRows: EntitySnapshotRow[] =
      entityIds.length > 0
        ? await this.db
            .select({
              id: entity.id,
              name: entity.name,
              code: entity.code,
              properties: entity.properties,
              workshopName: workshop.name,
            })
            .from(entity)
            .leftJoin(workshop, eq(entity.workshopId, workshop.id))
            .where(inArray(entity.id, entityIds))
        : [];
    const entityMap = new Map(entityRows.map((entityRow) => [entityRow.id, entityRow]));

    const primaryAliasRows =
      entityIds.length > 0
        ? await this.db
            .select({
              entityId: entityAlias.entityId,
              sourceType: entityAlias.sourceType,
            })
            .from(entityAlias)
            .where(
              and(inArray(entityAlias.entityId, entityIds), eq(entityAlias.isPrimary, true)),
            )
        : [];
    const aliasSourceMap = new Map(
      primaryAliasRows.map((aliasRow) => [aliasRow.entityId, aliasRow.sourceType]),
    );

    const items: MergeQueueItem[] = rows.map((row) => ({
      id: row.id,
      matchReason: row.matchReason ?? '',
      matchScore: row.matchScore,
      entityA: this.buildCandidate(
        row.entityAId,
        row.aName,
        row.aCode,
        entityMap,
        aliasSourceMap,
      ),
      entityB: this.buildCandidate(
        row.entityBId,
        row.bName,
        row.bCode,
        entityMap,
        aliasSourceMap,
      ),
      createdAt: row.createdAt.toISOString(),
    }));
    return { items, total };
  }

  private buildCandidate(
    entityId: string | null,
    snapName: string | null,
    snapCode: string | null,
    entityMap: Map<string, EntitySnapshotRow>,
    aliasSourceMap: Map<string, string>,
  ): MergeQueueCandidate {
    const entityRow = entityId ? entityMap.get(entityId) : undefined;
    if (!entityRow) {
      return {
        id: entityId ?? '',
        name: snapName ?? '',
        code: snapCode ?? null,
        sourceType: '',
      };
    }
    return {
      id: entityRow.id,
      name: entityRow.name,
      code: entityRow.code,
      model: readEntityProperties(entityRow.properties).model,
      sourceType: aliasSourceMap.get(entityRow.id) ?? '',
      workshopName: entityRow.workshopName ?? undefined,
    };
  }

  async listConflicts(
    projectId: string,
    status: string,
    offset: number,
    limit: number,
  ): Promise<ConflictListResponse> {
    const whereClause = and(
      eq(versionConflict.projectId, projectId),
      eq(versionConflict.status, status),
    );
    const rows = await this.db
      .select({
        id: versionConflict.id,
        entityId: versionConflict.entityId,
        entityName: entity.name,
        entityCode: entity.code,
        fieldName: versionConflict.fieldName,
        valueA: versionConflict.valueA,
        valueB: versionConflict.valueB,
        sourceA: versionConflict.sourceA,
        sourceB: versionConflict.sourceB,
      })
      .from(versionConflict)
      .leftJoin(entity, eq(versionConflict.entityId, entity.id))
      .where(whereClause)
      .orderBy(desc(versionConflict.createdAt))
      .limit(limit)
      .offset(offset);

    const totalRows = await this.db
      .select({ total: count() })
      .from(versionConflict)
      .where(whereClause);
    const total = Number(totalRows[0]?.total ?? 0);

    const items: ConflictListItem[] = rows.map((row) => ({
      id: row.id,
      entityId: row.entityId,
      entityName: row.entityName ?? '',
      entityCode: row.entityCode ?? '',
      fieldName: row.fieldName,
      valueA: row.valueA,
      valueB: row.valueB,
      sourceA: row.sourceA,
      sourceB: row.sourceB,
    }));
    return { items, total };
  }

  async getPendingCounts(projectId: string): Promise<PendingCounts> {
    const mergeRows = await this.db
      .select({ total: count() })
      .from(entityMergeQueue)
      .where(
        and(
          eq(entityMergeQueue.projectId, projectId),
          eq(entityMergeQueue.status, 'pending'),
        ),
      );
    const conflictRows = await this.db
      .select({ total: count() })
      .from(versionConflict)
      .where(
        and(
          eq(versionConflict.projectId, projectId),
          eq(versionConflict.status, 'pending'),
        ),
      );
    const classifyRows = await this.db
      .select({ total: count() })
      .from(siteRecord)
      .where(
        and(eq(siteRecord.projectId, projectId), eq(siteRecord.status, 'pending_classify')),
      );
    const approvalRows = await this.db
      .select({ total: count() })
      .from(approvalRequest)
      .where(
        and(eq(approvalRequest.projectId, projectId), eq(approvalRequest.status, 'pending')),
      );
    return {
      mergeQueueCount: Number(mergeRows[0]?.total ?? 0),
      conflictCount: Number(conflictRows[0]?.total ?? 0),
      classifyCount: Number(classifyRows[0]?.total ?? 0),
      approvalCount: Number(approvalRows[0]?.total ?? 0),
    };
  }
}
