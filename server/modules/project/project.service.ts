import { randomUUID } from 'crypto';

import {
  BadRequestException,
  Inject,
  Injectable,
  NotFoundException,
} from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  type PostgresJsDatabase,
  AuthNPaasService,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, desc, eq, ilike, inArray, or, sql } from 'drizzle-orm';

import {
  approvalRequest,
  backgroundTask,
  entity,
  entityAlias,
  entityMergeQueue,
  entityRelationship,
  fileWorkshop,
  project,
  projectFile,
  siteRecord,
  versionConflict,
  workshop,
} from '@server/database/schema';
import type {
  CreateProjectRequest,
  CreateWorkshopRequest,
  DashboardActivitiesResponse,
  DashboardSummary,
  DeleteProjectResponse,
  ProjectDetailInfo,
  ProjectStatistics,
  ProjectSummaryItem,
  UpdateProjectRequest,
  UpdateProjectResponse,
  UpdateWorkshopRequest,
  WorkshopSummary,
} from '@shared/api.interface';

interface ActivityRow {
  id: string;
  kind: 'file' | 'record';
  title: string;
  record_type: string | null;
  project_id: string;
  creator_id: string | null;
  created_at: string;
}

function pickI18nText(name: { zh_cn?: string; en_us?: string } | undefined): string {
  return name?.zh_cn || name?.en_us || '';
}

@Injectable()
export class ProjectService {
  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly authNPaasService: AuthNPaasService,
  ) {}

  getModuleStatus(): { module: string; status: string } {
    return { module: 'project', status: 'ok' };
  }

  async listProjects(keyword?: string, status?: string): Promise<{ items: ProjectSummaryItem[] }> {
    const conditions = [];
    if (keyword) {
      conditions.push(or(ilike(project.name, `%${keyword}%`), ilike(project.code, `%${keyword}%`)));
    }
    if (status) {
      conditions.push(eq(project.status, status));
    }

    const rows = await (conditions.length > 0
      ? this.db
          .select({
            id: project.id,
            name: project.name,
            code: project.code,
            status: project.status,
            createdAt: project.createdAt,
            workshopCount: this.db.$count(workshop, eq(workshop.projectId, project.id)),
            fileCount: this.db.$count(projectFile, eq(projectFile.projectId, project.id)),
            recordCount: this.db.$count(siteRecord, eq(siteRecord.projectId, project.id)),
            pendingCount: sql<number>`(
              (SELECT count(*) FROM entity_merge_queue q
                WHERE q.project_id = ${project.id} AND q.status = 'pending')
              + (SELECT count(*) FROM version_conflict c
                WHERE c.project_id = ${project.id} AND c.status = 'pending')
              + (SELECT count(*) FROM site_record r
                WHERE r.project_id = ${project.id} AND r.status = 'pending_classify')
            )`,
          })
          .from(project)
          .where(and(...conditions))
          .orderBy(desc(project.createdAt))
      : this.db
          .select({
            id: project.id,
            name: project.name,
            code: project.code,
            status: project.status,
            createdAt: project.createdAt,
            workshopCount: this.db.$count(workshop, eq(workshop.projectId, project.id)),
            fileCount: this.db.$count(projectFile, eq(projectFile.projectId, project.id)),
            recordCount: this.db.$count(siteRecord, eq(siteRecord.projectId, project.id)),
            pendingCount: sql<number>`(
              (SELECT count(*) FROM entity_merge_queue q
                WHERE q.project_id = ${project.id} AND q.status = 'pending')
              + (SELECT count(*) FROM version_conflict c
                WHERE c.project_id = ${project.id} AND c.status = 'pending')
              + (SELECT count(*) FROM site_record r
                WHERE r.project_id = ${project.id} AND r.status = 'pending_classify')
            )`,
          })
          .from(project)
          .orderBy(desc(project.createdAt)));

    return {
      items: rows.map((row) => ({
        id: row.id,
        name: row.name,
        code: row.code,
        status: row.status,
        workshopCount: Number(row.workshopCount),
        fileCount: Number(row.fileCount),
        recordCount: Number(row.recordCount),
        pendingCount: Number(row.pendingCount),
        createdAt: row.createdAt.toISOString(),
      })),
    };
  }

  async createProject(dto: CreateProjectRequest): Promise<{ id: string; agentApiKey: string }> {
    const agentApiKey = `ak_${randomUUID().replace(/-/g, '')}`;
    const inserted = await this.db
      .insert(project)
      .values({
        name: dto.name,
        code: dto.code,
        description: dto.description ?? null,
        agentApiKey,
      })
      .returning({ id: project.id });
    return { id: inserted[0].id, agentApiKey };
  }

  async updateProject(
    id: string,
    dto: UpdateProjectRequest,
  ): Promise<UpdateProjectResponse> {
    const exists = await this.db.$count(project, eq(project.id, id));
    if (exists === 0) {
      throw new NotFoundException('项目不存在');
    }

    const patch: Partial<typeof project.$inferInsert> = {};
    if (dto.name !== undefined) patch.name = dto.name;
    if (dto.code !== undefined) patch.code = dto.code;
    if (dto.description !== undefined) patch.description = dto.description;
    if (dto.status !== undefined) patch.status = dto.status;
    if (Object.keys(patch).length === 0) {
      throw new BadRequestException('未提供可更新字段');
    }

    const updated = await this.db
      .update(project)
      .set(patch)
      .where(eq(project.id, id))
      .returning({
        id: project.id,
        name: project.name,
        code: project.code,
        description: project.description,
        status: project.status,
      });
    if (updated.length === 0) {
      throw new NotFoundException('项目不存在');
    }
    const row = updated[0];
    return {
      id: row.id,
      name: row.name,
      code: row.code,
      description: row.description ?? undefined,
      status: row.status,
    };
  }

  async deleteProject(id: string): Promise<DeleteProjectResponse> {
    const exists = await this.db.$count(project, eq(project.id, id));
    if (exists === 0) {
      throw new NotFoundException('项目不存在');
    }

    await this.db.transaction(async (tx) => {
      const workshopRows = await tx
        .select({ id: workshop.id })
        .from(workshop)
        .where(eq(workshop.projectId, id));
      const fileRows = await tx
        .select({ id: projectFile.id })
        .from(projectFile)
        .where(eq(projectFile.projectId, id));
      const workshopIds = workshopRows.map((row: { id: string }) => row.id);
      const fileIds = fileRows.map((row: { id: string }) => row.id);

      if (workshopIds.length > 0) {
        await tx
          .delete(fileWorkshop)
          .where(inArray(fileWorkshop.workshopId, workshopIds));
      }
      if (fileIds.length > 0) {
        await tx
          .delete(fileWorkshop)
          .where(inArray(fileWorkshop.fileId, fileIds));
      }

      await tx.delete(workshop).where(eq(workshop.projectId, id));
      await tx.delete(siteRecord).where(eq(siteRecord.projectId, id));
      await tx.delete(entityAlias).where(eq(entityAlias.projectId, id));
      await tx.delete(entityMergeQueue).where(eq(entityMergeQueue.projectId, id));
      await tx.delete(versionConflict).where(eq(versionConflict.projectId, id));
      await tx.delete(entityRelationship).where(eq(entityRelationship.projectId, id));
      await tx.delete(backgroundTask).where(eq(backgroundTask.projectId, id));
      await tx.delete(entity).where(eq(entity.projectId, id));
      await tx.delete(projectFile).where(eq(projectFile.projectId, id));

      const deleted = await tx
        .delete(project)
        .where(eq(project.id, id))
        .returning({ id: project.id });
      if (deleted.length === 0) {
        throw new NotFoundException('项目不存在');
      }
    });

    return { id, deleted: true };
  }

  async getProjectDetail(id: string): Promise<ProjectDetailInfo> {
    const rows = await this.db
      .select({
        id: project.id,
        name: project.name,
        code: project.code,
        description: project.description,
        status: project.status,
        createdAt: project.createdAt,
      })
      .from(project)
      .where(eq(project.id, id));
    if (rows.length === 0) {
      throw new NotFoundException('项目不存在');
    }
    const row = rows[0];
    return {
      id: row.id,
      name: row.name,
      code: row.code,
      description: row.description ?? undefined,
      status: row.status,
      createdAt: row.createdAt.toISOString(),
    };
  }

  async getStatistics(projectId: string): Promise<ProjectStatistics> {
    const exists = await this.db.$count(project, eq(project.id, projectId));
    if (exists === 0) {
      throw new NotFoundException('项目不存在');
    }
    const [
      workshopCount,
      fileCount,
      recordCount,
      entityCount,
      pendingMergeCount,
      pendingSupplementCount,
    ] = await Promise.all([
      this.db.$count(workshop, eq(workshop.projectId, projectId)),
      this.db.$count(projectFile, eq(projectFile.projectId, projectId)),
      this.db.$count(siteRecord, eq(siteRecord.projectId, projectId)),
      this.db.$count(entity, eq(entity.projectId, projectId)),
      this.db.$count(entityMergeQueue, eq(entityMergeQueue.projectId, projectId)),
      this.db.$count(
        siteRecord,
        and(eq(siteRecord.projectId, projectId), eq(siteRecord.status, 'pending_supplement')),
      ),
    ]);
    return {
      workshopCount,
      fileCount,
      recordCount,
      entityCount,
      pendingMergeCount,
      pendingSupplementCount,
    };
  }

  async listWorkshops(projectId: string): Promise<{ items: WorkshopSummary[] }> {
    const rows = await this.db
      .select({
        id: workshop.id,
        name: workshop.name,
        code: workshop.code,
        description: workshop.description,
        sortOrder: workshop.sortOrder,
        fileCount: sql<number>`(
          SELECT count(DISTINCT fw.file_id) FROM file_workshop fw
          WHERE fw.workshop_id = ${workshop.id}
        )`,
        recordCount: this.db.$count(siteRecord, eq(siteRecord.workshopId, workshop.id)),
      })
      .from(workshop)
      .where(eq(workshop.projectId, projectId))
      .orderBy(workshop.sortOrder, workshop.name);

    return {
      items: rows.map((row) => ({
        id: row.id,
        name: row.name,
        code: row.code,
        description: row.description ?? undefined,
        sortOrder: row.sortOrder,
        fileCount: Number(row.fileCount),
        recordCount: Number(row.recordCount),
      })),
    };
  }

  async createWorkshop(
    projectId: string,
    dto: CreateWorkshopRequest,
  ): Promise<{ id: string }> {
    const exists = await this.db.$count(project, eq(project.id, projectId));
    if (exists === 0) {
      throw new NotFoundException('项目不存在');
    }
    const inserted = await this.db
      .insert(workshop)
      .values({
        projectId,
        name: dto.name,
        code: dto.code,
        description: dto.description ?? null,
        sortOrder: dto.sortOrder ?? 0,
      })
      .returning({ id: workshop.id });
    return { id: inserted[0].id };
  }

  async updateWorkshop(
    id: string,
    dto: UpdateWorkshopRequest,
    userId: string,
  ): Promise<{ id: string }> {
    const patch: Partial<typeof workshop.$inferInsert> = {};
    if (dto.name !== undefined) patch.name = dto.name;
    if (dto.code !== undefined) patch.code = dto.code;
    if (dto.description !== undefined) patch.description = dto.description;
    if (dto.sortOrder !== undefined) patch.sortOrder = dto.sortOrder;
    if (Object.keys(patch).length === 0) {
      throw new NotFoundException('未提供可更新字段');
    }
    patch.updatedAt = new Date();
    patch.updatedBy = userId;

    const updated = await this.db
      .update(workshop)
      .set(patch)
      .where(eq(workshop.id, id))
      .returning({ id: workshop.id });
    if (updated.length === 0) {
      throw new NotFoundException('车间不存在');
    }
    return { id: updated[0].id };
  }

  async deleteWorkshop(id: string): Promise<{ id: string }> {
    const deleted = await this.db
      .delete(workshop)
      .where(eq(workshop.id, id))
      .returning({ id: workshop.id });
    if (deleted.length === 0) {
      throw new NotFoundException('车间不存在');
    }
    return { id: deleted[0].id };
  }

  async dashboardSummary(): Promise<DashboardSummary> {
    const [
      projectCount,
      workshopCount,
      fileCount,
      recordCount,
      pendingMergeCount,
      pendingSupplementCount,
      pendingConflictCount,
      pendingClassifyCount,
      approvalCount,
    ] = await Promise.all([
      this.db.$count(project),
      this.db.$count(workshop),
      this.db.$count(projectFile),
      this.db.$count(siteRecord),
      this.db.$count(entityMergeQueue, eq(entityMergeQueue.status, 'pending')),
      this.db.$count(siteRecord, eq(siteRecord.status, 'pending_supplement')),
      this.db.$count(versionConflict, eq(versionConflict.status, 'pending')),
      this.db.$count(siteRecord, eq(siteRecord.status, 'pending_classify')),
      this.db.$count(approvalRequest, eq(approvalRequest.status, 'pending')),
    ]);
    return {
      projectCount,
      workshopCount,
      fileCount,
      recordCount,
      pendingMergeCount,
      pendingSupplementCount,
      pendingConflictCount,
      pendingClassifyCount,
      approvalCount,
    };
  }

  async dashboardActivities(limit: number): Promise<DashboardActivitiesResponse> {
    const result = await this.db.execute(sql`
      SELECT * FROM (
        SELECT f.id, 'file' AS kind, f.filename AS title, NULL::varchar AS record_type,
          f.project_id, (f._created_by).user_id AS creator_id, f._created_at AS created_at
        FROM project_file f
        UNION ALL
        SELECT r.id, 'record' AS kind, r.title AS title, r.record_type,
          r.project_id, (r._created_by).user_id AS creator_id, r._created_at AS created_at
        FROM site_record r
      ) t
      ORDER BY t.created_at DESC
      LIMIT ${limit}
    `);
    const rows = result as unknown as ActivityRow[];
    if (rows.length === 0) {
      return { items: [] };
    }

    const projectIds = [...new Set(rows.map((r) => r.project_id))];
    const projects = await this.db
      .select({ id: project.id, name: project.name })
      .from(project)
      .where(inArray(project.id, projectIds));
    const projectNameMap = new Map(projects.map((p) => [p.id, p.name]));

    const userIds = [
      ...new Set(rows.map((r) => r.creator_id).filter((id): id is string => Boolean(id))),
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

    return {
      items: rows.map((row) => ({
        id: row.id,
        kind: row.kind,
        title: row.title ?? '未命名',
        recordType: row.record_type ?? undefined,
        projectId: row.project_id,
        projectName: projectNameMap.get(row.project_id) ?? '未知项目',
        creatorId: row.creator_id ?? undefined,
        creatorName: (row.creator_id && userNameMap.get(row.creator_id)) || '系统',
        createdAt: new Date(row.created_at).toISOString(),
      })),
    };
  }
}
