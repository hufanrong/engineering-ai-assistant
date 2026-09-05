import { Inject, Injectable } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, count, eq, inArray, type SQL } from 'drizzle-orm';

import type { GraphDataResponse, GraphNode } from '@shared/api.interface';
import { entity, entityAlias, entityRelationship, workshop } from '@server/database/schema';

@Injectable()
export class GraphService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async getGraphData(
    projectId: string,
    entityTypes?: string[],
  ): Promise<GraphDataResponse> {
    const conditions: SQL[] = [eq(entity.projectId, projectId)];
    if (entityTypes && entityTypes.length > 0) {
      conditions.push(inArray(entity.entityType, entityTypes));
    }

    const rows = await this.db
      .select({
        id: entity.id,
        name: entity.name,
        code: entity.code,
        entityType: entity.entityType,
        workshopName: workshop.name,
      })
      .from(entity)
      .leftJoin(workshop, eq(entity.workshopId, workshop.id))
      .where(and(...conditions));

    const nodeIds: string[] = rows.map((row) => row.id);

    const aliasCountMap = new Map<string, number>();
    if (nodeIds.length > 0) {
      const aliasRows = await this.db
        .select({ entityId: entityAlias.entityId, total: count() })
        .from(entityAlias)
        .where(inArray(entityAlias.entityId, nodeIds))
        .groupBy(entityAlias.entityId);
      for (const aliasRow of aliasRows) {
        aliasCountMap.set(aliasRow.entityId, Number(aliasRow.total));
      }
    }

    const nodes: GraphNode[] = rows.map((row) => ({
      id: row.id,
      name: row.name,
      code: row.code,
      entityType: row.entityType,
      workshopName: row.workshopName ?? undefined,
      aliasCount: aliasCountMap.get(row.id) ?? 0,
    }));

    const edgeRows =
      nodeIds.length > 0
        ? await this.db
            .select({
              id: entityRelationship.id,
              sourceEntityId: entityRelationship.sourceEntityId,
              targetEntityId: entityRelationship.targetEntityId,
              relationshipType: entityRelationship.relationshipType,
            })
            .from(entityRelationship)
            .where(
              and(
                eq(entityRelationship.projectId, projectId),
                inArray(entityRelationship.sourceEntityId, nodeIds),
                inArray(entityRelationship.targetEntityId, nodeIds),
              ),
            )
        : [];

    const edges = edgeRows.map((edgeRow) => ({
      id: edgeRow.id,
      source: edgeRow.sourceEntityId,
      target: edgeRow.targetEntityId,
      relationshipType: edgeRow.relationshipType,
    }));

    return { nodes, edges };
  }
}
