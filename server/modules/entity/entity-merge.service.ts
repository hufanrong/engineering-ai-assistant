import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { eq } from 'drizzle-orm';

import { entity, entityAlias, entityMergeQueue, versionConflict } from '@server/database/schema';
import { readEntityProperties } from './entity-property.util';
import {
  COMPOSITE_MATCH_THRESHOLD,
  findComposite,
  findSimilarByCode,
  type CompositeMatch,
  type ExistingEntityRow,
} from './entity-similarity.util';

export interface ExtractedEntity {
  code?: string;
  name?: string;
  model?: string;
  spec?: string;
  entityType?: string;
}

@Injectable()
export class EntityMergeService {
  private readonly logger = new Logger(EntityMergeService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  /**
   * 解析产物实体归并入口：编号精确/相似匹配自动归并，
   * 名称+型号+车间综合相似进入待确认队列，无匹配则新建独立实体。
   * 单条失败仅记录日志，不中断整体解析任务。
   */
  async ingestEntities(
    projectId: string,
    workshopId: string | null,
    sourceFileId: string,
    sourceType: string,
    entities: ExtractedEntity[],
  ): Promise<void> {
    const existingRows: ExistingEntityRow[] = await this.db
      .select({
        id: entity.id,
        entityType: entity.entityType,
        name: entity.name,
        code: entity.code,
        workshopId: entity.workshopId,
        properties: entity.properties,
      })
      .from(entity)
      .where(eq(entity.projectId, projectId));

    for (const item of entities) {
      try {
        await this.processOne(
          item,
          existingRows,
          projectId,
          workshopId,
          sourceFileId,
          sourceType,
        );
      } catch (error) {
        this.logger.error(
          `ingestEntities single item failed: ${JSON.stringify({
            projectId,
            sourceFileId,
            itemCode: item.code ?? null,
            itemName: item.name ?? null,
            error: error instanceof Error ? error.message : String(error),
          })}`,
        );
      }
    }
  }

  private async processOne(
    item: ExtractedEntity,
    existingRows: ExistingEntityRow[],
    projectId: string,
    workshopId: string | null,
    sourceFileId: string,
    sourceType: string,
  ): Promise<void> {
    const name: string = (item.name ?? '').trim();
    const code: string | null = item.code ? item.code.trim() : null;
    const entityType: string = item.entityType || 'equipment';
    if (!name && !code) {
      return;
    }

    const exact = code
      ? existingRows.find(
          (row: ExistingEntityRow) =>
            row.code !== null && row.code.toLowerCase() === code.toLowerCase(),
        )
      : undefined;
    if (exact) {
      await this.autoMerge(exact, item, projectId, sourceFileId, sourceType);
      return;
    }

    const similar = findSimilarByCode(existingRows, code, workshopId, entityType);
    if (similar) {
      await this.autoMerge(similar, item, projectId, sourceFileId, sourceType);
      return;
    }

    const composite = findComposite(existingRows, item, workshopId);
    if (composite && composite.score > COMPOSITE_MATCH_THRESHOLD) {
      await this.createPendingPair(
        composite,
        item,
        entityType,
        projectId,
        workshopId,
        sourceFileId,
        sourceType,
      );
      return;
    }

    await this.createStandalone(
      item,
      entityType,
      projectId,
      workshopId,
      sourceFileId,
      sourceType,
    );
  }

  private async insertAlias(
    entityId: string,
    item: ExtractedEntity,
    isPrimary: boolean,
    projectId: string,
    sourceFileId: string,
    sourceType: string,
  ): Promise<void> {
    await this.db.insert(entityAlias).values({
      projectId,
      entityId,
      aliasName: item.name ? item.name : null,
      aliasCode: item.code ? item.code : null,
      sourceType,
      isPrimary,
      status: 'confirmed',
      confidence: 1,
      sourceFileId,
    });
  }

  private async autoMerge(
    target: ExistingEntityRow,
    item: ExtractedEntity,
    projectId: string,
    sourceFileId: string,
    sourceType: string,
  ): Promise<void> {
    await this.insertAlias(target.id, item, false, projectId, sourceFileId, sourceType);

    const props = readEntityProperties(target.properties);
    const conflicts: Array<typeof versionConflict.$inferInsert> = [];
    const pairs: Array<{ fieldName: string; old: string; new: string }> = [
      { fieldName: 'model', old: props.model ?? '', new: item.model ?? '' },
      { fieldName: 'spec', old: props.spec ?? '', new: item.spec ?? '' },
    ];
    for (const pair of pairs) {
      if (pair.old && pair.new && pair.old !== pair.new) {
        conflicts.push({
          projectId,
          entityId: target.id,
          fieldName: pair.fieldName,
          valueA: pair.old,
          valueB: pair.new,
          sourceA: 'existing',
          sourceB: sourceType,
          status: 'pending',
        });
      }
    }
    if (conflicts.length > 0) {
      await this.db.insert(versionConflict).values(conflicts);
    }

    await this.db
      .update(entity)
      .set({ mergeStatus: 'merged', updatedAt: new Date() })
      .where(eq(entity.id, target.id));
  }

  private async createPendingPair(
    composite: CompositeMatch,
    item: ExtractedEntity,
    entityType: string,
    projectId: string,
    workshopId: string | null,
    sourceFileId: string,
    sourceType: string,
  ): Promise<void> {
    const inserted = await this.db
      .insert(entity)
      .values({
        projectId,
        entityType,
        name: item.name ?? '',
        code: item.code ? item.code : null,
        workshopId,
        properties: { model: item.model ?? '', spec: item.spec ?? '' },
        sourceFileId,
        mergeStatus: 'pending',
      })
      .returning({ id: entity.id });
    const newEntityId = inserted[0].id;

    await this.insertAlias(newEntityId, item, true, projectId, sourceFileId, sourceType);

    await this.db
      .update(entity)
      .set({ mergeStatus: 'pending', updatedAt: new Date() })
      .where(eq(entity.id, composite.candidate.id));

    await this.db.insert(entityMergeQueue).values({
      projectId,
      entityAId: composite.candidate.id,
      entityBId: newEntityId,
      matchReason: composite.reason,
      matchScore: composite.score,
      aName: composite.candidate.name,
      aCode: composite.candidate.code,
      bName: item.name ?? '',
      bCode: item.code ? item.code : null,
      status: 'pending',
    });
  }

  private async createStandalone(
    item: ExtractedEntity,
    entityType: string,
    projectId: string,
    workshopId: string | null,
    sourceFileId: string,
    sourceType: string,
  ): Promise<void> {
    const inserted = await this.db
      .insert(entity)
      .values({
        projectId,
        entityType,
        name: item.name ?? '',
        code: item.code ? item.code : null,
        workshopId,
        properties: { model: item.model ?? '', spec: item.spec ?? '' },
        sourceFileId,
        mergeStatus: 'standalone',
      })
      .returning({ id: entity.id });
    const newEntityId = inserted[0].id;

    await this.insertAlias(newEntityId, item, true, projectId, sourceFileId, sourceType);
  }
}
