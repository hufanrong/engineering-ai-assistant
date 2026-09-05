import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, count, desc, eq, ilike, inArray, or, type SQL } from 'drizzle-orm';
import { alias } from 'drizzle-orm/pg-core';

import type {
  EntityAliasItem,
  EntityConflictItem,
  EntityDetail,
  EntityListItem,
  EntityListResponse,
  EntityRelationshipItem,
} from '@shared/api.interface';
import {
  entity,
  entityAlias,
  entityRelationship,
  versionConflict,
  workshop,
} from '@server/database/schema';
import { readEntityProperties } from './entity-property.util';

export interface EntityListParams {
  entityType?: string;
  workshopId?: string;
  keyword?: string;
  mergeStatus?: string;
  offset: number;
  limit: number;
}

@Injectable()
export class EntityService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async listEntities(
    projectId: string,
    params: EntityListParams,
  ): Promise<EntityListResponse> {
    const conditions: SQL[] = [eq(entity.projectId, projectId)];
    if (params.entityType) {
      conditions.push(eq(entity.entityType, params.entityType));
    }
    if (params.workshopId) {
      conditions.push(eq(entity.workshopId, params.workshopId));
    }
    if (params.mergeStatus) {
      conditions.push(eq(entity.mergeStatus, params.mergeStatus));
    }
    if (params.keyword) {
      const keywordFilter = or(
        ilike(entity.name, `%${params.keyword}%`),
        ilike(entity.code, `%${params.keyword}%`),
      );
      if (keywordFilter) {
        conditions.push(keywordFilter);
      }
    }
    const whereClause = and(...conditions);

    const rows = await this.db
      .select({
        id: entity.id,
        code: entity.code,
        name: entity.name,
        entityType: entity.entityType,
        properties: entity.properties,
        mergeStatus: entity.mergeStatus,
        workshopName: workshop.name,
      })
      .from(entity)
      .leftJoin(workshop, eq(entity.workshopId, workshop.id))
      .where(whereClause)
      .orderBy(desc(entity.createdAt))
      .limit(params.limit)
      .offset(params.offset);

    const totalRows = await this.db
      .select({ total: count() })
      .from(entity)
      .where(whereClause);
    const total = Number(totalRows[0]?.total ?? 0);

    const entityIds: string[] = rows.map((row) => row.id);
    const aliasRows =
      entityIds.length > 0
        ? await this.db
            .select({ entityId: entityAlias.entityId, total: count() })
            .from(entityAlias)
            .where(inArray(entityAlias.entityId, entityIds))
            .groupBy(entityAlias.entityId)
        : [];
    const aliasCountMap = new Map<string, number>();
    for (const aliasRow of aliasRows) {
      aliasCountMap.set(aliasRow.entityId, Number(aliasRow.total));
    }

    const items: EntityListItem[] = rows.map((row) => ({
      id: row.id,
      code: row.code,
      name: row.name,
      entityType: row.entityType,
      model: readEntityProperties(row.properties).model,
      workshopName: row.workshopName ?? undefined,
      aliasCount: aliasCountMap.get(row.id) ?? 0,
      mergeStatus: row.mergeStatus,
    }));
    return { items, total };
  }

  async getEntityDetail(entityId: string): Promise<EntityDetail> {
    const rows = await this.db
      .select({
        id: entity.id,
        projectId: entity.projectId,
        code: entity.code,
        name: entity.name,
        entityType: entity.entityType,
        properties: entity.properties,
        mergeStatus: entity.mergeStatus,
        workshopId: entity.workshopId,
        workshopName: workshop.name,
      })
      .from(entity)
      .leftJoin(workshop, eq(entity.workshopId, workshop.id))
      .where(eq(entity.id, entityId))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('实体不存在');
    }
    const row = rows[0];

    const aliasRows = await this.db
      .select({
        id: entityAlias.id,
        aliasName: entityAlias.aliasName,
        aliasCode: entityAlias.aliasCode,
        sourceType: entityAlias.sourceType,
        isPrimary: entityAlias.isPrimary,
        status: entityAlias.status,
      })
      .from(entityAlias)
      .where(eq(entityAlias.entityId, entityId))
      .orderBy(desc(entityAlias.isPrimary));
    const aliases: EntityAliasItem[] = aliasRows.map((aliasRow) => ({
      id: aliasRow.id,
      aliasName: aliasRow.aliasName,
      aliasCode: aliasRow.aliasCode,
      sourceType: aliasRow.sourceType,
      isPrimary: aliasRow.isPrimary,
      status: aliasRow.status,
    }));

    const relationships = await this.listRelationships(entityId);
    const conflictRows = await this.db
      .select({
        id: versionConflict.id,
        fieldName: versionConflict.fieldName,
        status: versionConflict.status,
      })
      .from(versionConflict)
      .where(eq(versionConflict.entityId, entityId));
    const conflicts: EntityConflictItem[] = conflictRows.map((conflictRow) => ({
      id: conflictRow.id,
      fieldName: conflictRow.fieldName,
      status: conflictRow.status,
    }));

    return {
      id: row.id,
      projectId: row.projectId,
      code: row.code,
      name: row.name,
      entityType: row.entityType,
      properties: readEntityProperties(row.properties),
      workshop:
        row.workshopId && row.workshopName
          ? { id: row.workshopId, name: row.workshopName }
          : undefined,
      mergeStatus: row.mergeStatus,
      aliases,
      relationships,
      conflicts,
    };
  }

  private async listRelationships(entityId: string): Promise<EntityRelationshipItem[]> {
    const targetEntity = alias(entity, 'target_entity');
    const outRows = await this.db
      .select({
        id: entityRelationship.id,
        relationshipType: entityRelationship.relationshipType,
        targetId: targetEntity.id,
        targetName: targetEntity.name,
        targetCode: targetEntity.code,
        targetEntityType: targetEntity.entityType,
      })
      .from(entityRelationship)
      .innerJoin(targetEntity, eq(entityRelationship.targetEntityId, targetEntity.id))
      .where(eq(entityRelationship.sourceEntityId, entityId));

    const sourceEntity = alias(entity, 'source_entity');
    const inRows = await this.db
      .select({
        id: entityRelationship.id,
        relationshipType: entityRelationship.relationshipType,
        sourceId: sourceEntity.id,
        sourceName: sourceEntity.name,
        sourceCode: sourceEntity.code,
        sourceEntityType: sourceEntity.entityType,
      })
      .from(entityRelationship)
      .innerJoin(sourceEntity, eq(entityRelationship.sourceEntityId, sourceEntity.id))
      .where(eq(entityRelationship.targetEntityId, entityId));

    return [
      ...outRows.map((row) => ({
        id: row.id,
        relationshipType: row.relationshipType,
        targetEntity: {
          id: row.targetId,
          name: row.targetName,
          code: row.targetCode,
          entityType: row.targetEntityType,
        },
        direction: 'out' as const,
      })),
      ...inRows.map((row) => ({
        id: row.id,
        relationshipType: row.relationshipType,
        targetEntity: {
          id: row.sourceId,
          name: row.sourceName,
          code: row.sourceCode,
          entityType: row.sourceEntityType,
        },
        direction: 'in' as const,
      })),
    ];
  }
}
