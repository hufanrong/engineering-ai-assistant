import { randomUUID } from 'node:crypto';

import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { count, eq } from 'drizzle-orm';

import {
  backgroundTask,
  entity,
  entityRelationship,
  platformMaterial,
  platformProcess,
  platformStandard,
  project,
  projectFile,
  siteRecord,
} from '@server/database/schema';
import type {
  PlatformLibInfo,
  RepositoryInfo,
  RepositoryStats,
  RotateKeyResponse,
} from '@shared/api.interface';

@Injectable()
export class RepositoryService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async getRepositoryInfo(
    projectId: string,
    appId: string,
  ): Promise<RepositoryInfo> {
    const projectRows = await this.db
      .select({
        id: project.id,
        name: project.name,
        agentApiKey: project.agentApiKey,
      })
      .from(project)
      .where(eq(project.id, projectId))
      .limit(1);
    if (projectRows.length === 0) {
      throw new NotFoundException(`项目不存在: ${projectId}`);
    }
    const projectRow = projectRows[0];

    const [
      fileRows,
      entityRows,
      relationshipRows,
      recordRows,
      taskRows,
      standardRows,
      materialRows,
      processRows,
    ] = await Promise.all([
      this.db
        .select({ value: count() })
        .from(projectFile)
        .where(eq(projectFile.projectId, projectId)),
      this.db
        .select({ value: count() })
        .from(entity)
        .where(eq(entity.projectId, projectId)),
      this.db
        .select({ value: count() })
        .from(entityRelationship)
        .where(eq(entityRelationship.projectId, projectId)),
      this.db
        .select({ value: count() })
        .from(siteRecord)
        .where(eq(siteRecord.projectId, projectId)),
      this.db
        .select({ value: count() })
        .from(backgroundTask)
        .where(eq(backgroundTask.projectId, projectId)),
      this.db.select({ value: count() }).from(platformStandard),
      this.db.select({ value: count() }).from(platformMaterial),
      this.db.select({ value: count() }).from(platformProcess),
    ]);

    const toNumber = (rows: Array<{ value: number }>): number =>
      Number(rows[0]?.value ?? 0);

    const stats: RepositoryStats = {
      fileCount: toNumber(fileRows),
      entityCount: toNumber(entityRows),
      relationshipCount: toNumber(relationshipRows),
      recordCount: toNumber(recordRows),
      taskCount: toNumber(taskRows),
    };

    const platformLib: PlatformLibInfo = {
      standardsCount: toNumber(standardRows),
      materialsCount: toNumber(materialRows),
      processesCount: toNumber(processRows),
    };

    return {
      projectId: projectRow.id,
      projectName: projectRow.name,
      apiEndpoint: `/app/${appId}/api`,
      searchApi: `/app/${appId}/api/rag/search`,
      agentApiKey: projectRow.agentApiKey,
      localPaths: {
        database: `postgres://app_db/app_${appId}`,
        files: `/app/${appId}/storage`,
      },
      stats,
      platformLib,
    };
  }

  async rotateKey(projectId: string): Promise<RotateKeyResponse> {
    const newKey = `ak_${randomUUID().replace(/-/g, '')}`;
    const updated = await this.db
      .update(project)
      .set({ agentApiKey: newKey, updatedAt: new Date() })
      .where(eq(project.id, projectId))
      .returning({ agentApiKey: project.agentApiKey });
    if (updated.length === 0) {
      throw new NotFoundException(`项目不存在: ${projectId}`);
    }
    return { agentApiKey: updated[0].agentApiKey };
  }
}
