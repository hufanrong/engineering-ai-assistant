import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
  AuthNPaasService,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, desc, eq, ilike, inArray } from 'drizzle-orm';

import {
  backgroundTask,
  entity,
  fileWorkshop,
  project,
  projectFile,
  workshop,
} from '@server/database/schema';
import type {
  CreateFileRequest,
  CreateFileResponse,
  DeleteViaApprovalResponse,
  FileDetail,
  FileListItem,
  FileListResponse,
  FileVersionItem,
} from '@shared/api.interface';
import { ApprovalService } from '../approval/approval.service';
import { isSuperAdmin, type UserContextWithRoles } from '../approval/user-context';
import { FileParseService, isParseableFileType } from './file-parse.service';

interface FileListFilters {
  workshopId?: string;
  fileType?: string;
  parseStatus?: string;
  keyword?: string;
  offset: number;
  limit: number;
}

function pickI18nText(name: { zh_cn?: string; en_us?: string } | undefined): string {
  return name?.zh_cn || name?.en_us || '';
}

@Injectable()
export class FileService {
  private readonly logger = new Logger(FileService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly authNPaasService: AuthNPaasService,
    private readonly fileParseService: FileParseService,
    private readonly approvalService: ApprovalService,
  ) {}

  getModuleStatus(): { module: string; status: string } {
    return { module: 'file', status: 'ok' };
  }

  async createFile(
    projectId: string,
    dto: CreateFileRequest,
    userId: string,
  ): Promise<CreateFileResponse> {
    const projectExists = await this.db.$count(project, eq(project.id, projectId));
    if (projectExists === 0) {
      throw new NotFoundException('项目不存在');
    }

    const duplicated = await this.db
      .select({
        id: projectFile.id,
        versionNo: projectFile.versionNo,
        isLatest: projectFile.isLatest,
      })
      .from(projectFile)
      .where(and(eq(projectFile.projectId, projectId), eq(projectFile.sha256, dto.sha256)))
      .limit(1);

    if (duplicated.length > 0) {
      return {
        id: duplicated[0].id,
        versionNo: duplicated[0].versionNo,
        isLatest: duplicated[0].isLatest,
        duplicated: true,
        message: '文件已存在，已跳过',
      };
    }

    const latest = await this.db
      .select({ versionNo: projectFile.versionNo })
      .from(projectFile)
      .where(and(eq(projectFile.projectId, projectId), eq(projectFile.filename, dto.filename)))
      .orderBy(desc(projectFile.versionNo))
      .limit(1);
    const versionNo = latest.length > 0 ? latest[0].versionNo + 1 : 1;
    if (versionNo > 1) {
      await this.db
        .update(projectFile)
        .set({ isLatest: false, updatedAt: new Date(), updatedBy: userId })
        .where(
          and(
            eq(projectFile.projectId, projectId),
            eq(projectFile.filename, dto.filename),
            eq(projectFile.isLatest, true),
          ),
        );
    }

    const parseable = isParseableFileType(dto.fileType);
    const inserted = await this.db
      .insert(projectFile)
      .values({
        projectId,
        filename: dto.filename,
        fileUrl: dto.fileUrl,
        fileType: dto.fileType,
        fileSize: dto.fileSize,
        sha256: dto.sha256,
        source: dto.source,
        parseStatus: parseable ? 'pending' : 'skipped',
        versionNo,
        isLatest: true,
        createdBy: userId,
        updatedBy: userId,
      })
      .returning({ id: projectFile.id });
    const fileId = inserted[0].id;

    if (dto.workshopIds && dto.workshopIds.length > 0) {
      await this.db.insert(fileWorkshop).values(
        dto.workshopIds.map((workshopId: string) => ({
          fileId,
          workshopId,
          createdBy: userId,
          updatedBy: userId,
        })),
      );
    }

    let taskId: string | undefined;
    if (parseable) {
      const task = await this.db
        .insert(backgroundTask)
        .values({
          projectId,
          fileId,
          taskType: 'parse',
          status: 'pending',
          progress: 0,
          createdBy: userId,
          updatedBy: userId,
        })
        .returning({ id: backgroundTask.id });
      taskId = task[0].id;

      void this.fileParseService.runParsePipeline(taskId, fileId, dto.fileUrl).catch(
        (error: unknown) => {
          this.logger.error(
            `parse pipeline crashed, taskId=${taskId}, fileId=${fileId}: ${JSON.stringify(
              error instanceof Error ? error.stack : String(error),
            )}`,
          );
        },
      );
    }

    return {
      id: fileId,
      versionNo,
      isLatest: true,
      duplicated: false,
      message: taskId ? '已提交解析任务' : undefined,
    };
  }

  async deleteFileWithApproval(
    id: string,
    userContext: UserContextWithRoles,
  ): Promise<DeleteViaApprovalResponse> {
    const rows = await this.db
      .select({
        id: projectFile.id,
        filename: projectFile.filename,
        projectId: projectFile.projectId,
      })
      .from(projectFile)
      .where(eq(projectFile.id, id))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('文件不存在');
    }
    const fileRow = rows[0];

    if (isSuperAdmin(userContext)) {
      await this.db.delete(fileWorkshop).where(eq(fileWorkshop.fileId, id));
      await this.db.delete(backgroundTask).where(eq(backgroundTask.fileId, id));
      await this.db.delete(projectFile).where(eq(projectFile.id, id));
      return { approvalRequestId: '', status: 'executed', message: '文件已删除' };
    }

    const approvalRequestId = await this.approvalService.createApprovalRequest({
      projectId: fileRow.projectId,
      requestType: 'delete_file',
      targetId: id,
      payload: {
        fileId: id,
        filename: fileRow.filename,
        projectId: fileRow.projectId,
      },
      summary: `删除文件：${fileRow.filename}`,
      requesterId: userContext.userId,
    });
    return {
      approvalRequestId,
      status: 'pending',
      message: '已提交审批，等待超级管理员审批',
    };
  }

  async listFiles(projectId: string, filters: FileListFilters): Promise<FileListResponse> {
    const conditions = [eq(projectFile.projectId, projectId)];
    if (filters.workshopId) {
      conditions.push(
        inArray(
          projectFile.id,
          this.db
            .select({ id: fileWorkshop.fileId })
            .from(fileWorkshop)
            .where(eq(fileWorkshop.workshopId, filters.workshopId)),
        ),
      );
    }
    if (filters.fileType) {
      conditions.push(eq(projectFile.fileType, filters.fileType));
    }
    if (filters.parseStatus) {
      conditions.push(eq(projectFile.parseStatus, filters.parseStatus));
    }
    if (filters.keyword) {
      conditions.push(ilike(projectFile.filename, `%${filters.keyword}%`));
    }
    const where = and(...conditions);

    const total = await this.db.$count(projectFile, where);
    const rows = await this.db
      .select({
        id: projectFile.id,
        filename: projectFile.filename,
        fileType: projectFile.fileType,
        fileSize: projectFile.fileSize,
        versionNo: projectFile.versionNo,
        isLatest: projectFile.isLatest,
        parseStatus: projectFile.parseStatus,
        createdBy: projectFile.createdBy,
        createdAt: projectFile.createdAt,
      })
      .from(projectFile)
      .where(where)
      .orderBy(desc(projectFile.createdAt))
      .limit(filters.limit)
      .offset(filters.offset);

    if (rows.length === 0) {
      return { items: [], total: Number(total) };
    }

    const fileIds = rows.map((row) => row.id);
    const workshopRows = await this.db
      .select({ fileId: fileWorkshop.fileId, name: workshop.name })
      .from(fileWorkshop)
      .innerJoin(workshop, eq(fileWorkshop.workshopId, workshop.id))
      .where(inArray(fileWorkshop.fileId, fileIds));
    const workshopMap = new Map<string, string[]>();
    for (const row of workshopRows) {
      workshopMap.set(row.fileId, [...(workshopMap.get(row.fileId) ?? []), row.name]);
    }

    const userIds = [
      ...new Set(rows.map((row) => row.createdBy).filter((id): id is string => Boolean(id))),
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

    const items: FileListItem[] = rows.map((row) => ({
      id: row.id,
      filename: row.filename,
      fileType: row.fileType,
      fileSize: row.fileSize,
      versionNo: row.versionNo,
      isLatest: row.isLatest,
      parseStatus: row.parseStatus,
      workshopNames: workshopMap.get(row.id) ?? [],
      creatorName: (row.createdBy && userNameMap.get(row.createdBy)) || '系统',
      createdAt: row.createdAt.toISOString(),
    }));
    return { items, total: Number(total) };
  }

  async getFileDetail(id: string): Promise<FileDetail> {
    const rows = await this.db.select().from(projectFile).where(eq(projectFile.id, id)).limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('文件不存在');
    }
    const file = rows[0];

    const versions = await this.db
      .select({
        id: projectFile.id,
        versionNo: projectFile.versionNo,
        filename: projectFile.filename,
        fileUrl: projectFile.fileUrl,
        createdBy: projectFile.createdBy,
        createdAt: projectFile.createdAt,
      })
      .from(projectFile)
      .where(and(eq(projectFile.projectId, file.projectId), eq(projectFile.filename, file.filename)))
      .orderBy(desc(projectFile.versionNo));

    const relatedEntities = await this.db
      .select({ id: entity.id, name: entity.name, code: entity.code })
      .from(entity)
      .where(
        inArray(
          entity.sourceFileId,
          versions.map((v) => v.id),
        ),
      );
    const workshops = await this.db
      .select({ id: workshop.id, name: workshop.name })
      .from(fileWorkshop)
      .innerJoin(workshop, eq(fileWorkshop.workshopId, workshop.id))
      .where(eq(fileWorkshop.fileId, id));

    const versionUserIds = [
      ...new Set(versions.map((v) => v.createdBy).filter((uid): uid is string => Boolean(uid))),
    ];
    const userNameMap = new Map<string, string>();
    if (versionUserIds.length > 0) {
      const users = await this.authNPaasService.listUsersByIds(versionUserIds);
      for (const user of users) {
        if (user) {
          userNameMap.set(user.miaodaUserID, pickI18nText(user.name));
        }
      }
    }
    const versionItems: FileVersionItem[] = versions.map((v) => ({
      versionNo: v.versionNo,
      filename: v.filename,
      fileUrl: v.fileUrl,
      creatorName: (v.createdBy && userNameMap.get(v.createdBy)) || '系统',
      createdAt: v.createdAt.toISOString(),
    }));

    return {
      id: file.id,
      filename: file.filename,
      fileUrl: file.fileUrl,
      fileType: file.fileType,
      fileSize: file.fileSize,
      sha256: file.sha256,
      parseStatus: file.parseStatus,
      parseError: file.parseError ?? undefined,
      versionNo: file.versionNo,
      workshops,
      relatedEntities,
      versions: versionItems,
    };
  }
}
