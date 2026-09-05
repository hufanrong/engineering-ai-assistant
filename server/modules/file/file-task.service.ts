import { Inject, Injectable, Logger, NotFoundException } from '@nestjs/common';
import {
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, desc, eq, inArray } from 'drizzle-orm';

import {
  backgroundTask,
  projectFile,
  siteRecord,
} from '@server/database/schema';
import type {
  TaskListItem,
  TaskListResponse,
  TaskRetryResponse,
} from '@shared/api.interface';
import { FileParseService } from './file-parse.service';

@Injectable()
export class FileTaskService {
  private readonly logger = new Logger(FileTaskService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly fileParseService: FileParseService,
  ) {}

  async listTasks(
    projectId: string,
    status: string | undefined,
    offset: number,
    limit: number,
  ): Promise<TaskListResponse> {
    const conditions = [eq(backgroundTask.projectId, projectId)];
    if (status) {
      conditions.push(eq(backgroundTask.status, status));
    }
    const where = and(...conditions);

    const total = await this.db.$count(backgroundTask, where);
    const rows = await this.db
      .select({
        id: backgroundTask.id,
        taskType: backgroundTask.taskType,
        status: backgroundTask.status,
        progress: backgroundTask.progress,
        message: backgroundTask.message,
        fileId: backgroundTask.fileId,
        recordId: backgroundTask.recordId,
        createdAt: backgroundTask.createdAt,
      })
      .from(backgroundTask)
      .where(where)
      .orderBy(desc(backgroundTask.createdAt))
      .limit(limit)
      .offset(offset);

    if (rows.length === 0) {
      return { items: [], total: Number(total) };
    }

    const fileIds = [
      ...new Set(rows.map((r) => r.fileId).filter((fid): fid is string => Boolean(fid))),
    ];
    const recordIds = [
      ...new Set(rows.map((r) => r.recordId).filter((rid): rid is string => Boolean(rid))),
    ];

    const fileNameMap = new Map<string, string>();
    if (fileIds.length > 0) {
      const fileRows = await this.db
        .select({ id: projectFile.id, filename: projectFile.filename })
        .from(projectFile)
        .where(inArray(projectFile.id, fileIds));
      for (const row of fileRows) {
        fileNameMap.set(row.id, row.filename);
      }
    }
    const recordTitleMap = new Map<string, string>();
    if (recordIds.length > 0) {
      const recordRows = await this.db
        .select({ id: siteRecord.id, title: siteRecord.title })
        .from(siteRecord)
        .where(inArray(siteRecord.id, recordIds));
      for (const row of recordRows) {
        recordTitleMap.set(row.id, row.title ?? '未命名记录');
      }
    }

    const items: TaskListItem[] = rows.map((row) => ({
      id: row.id,
      taskType: row.taskType,
      status: row.status,
      progress: row.progress,
      message: row.message ?? undefined,
      fileName: row.fileId ? fileNameMap.get(row.fileId) : undefined,
      recordTitle: row.recordId ? recordTitleMap.get(row.recordId) : undefined,
      createdAt: row.createdAt.toISOString(),
    }));
    return { items, total: Number(total) };
  }

  async retryTask(taskId: string): Promise<TaskRetryResponse> {
    const rows = await this.db
      .select({
        id: backgroundTask.id,
        status: backgroundTask.status,
        fileId: backgroundTask.fileId,
      })
      .from(backgroundTask)
      .where(eq(backgroundTask.id, taskId))
      .limit(1);
    if (rows.length === 0) {
      throw new NotFoundException('任务不存在');
    }
    const task = rows[0];
    if (task.status !== 'failed') {
      throw new NotFoundException('仅失败的任务可以重试');
    }
    if (!task.fileId) {
      throw new NotFoundException('任务未关联文件，无法重试');
    }

    const fileRows = await this.db
      .select({ fileUrl: projectFile.fileUrl })
      .from(projectFile)
      .where(eq(projectFile.id, task.fileId))
      .limit(1);
    if (fileRows.length === 0) {
      throw new NotFoundException('任务关联文件不存在');
    }

    await this.db
      .update(backgroundTask)
      .set({ status: 'pending', progress: 0, message: null, updatedAt: new Date() })
      .where(eq(backgroundTask.id, taskId));
    await this.db
      .update(projectFile)
      .set({ parseStatus: 'pending', parseError: null, updatedAt: new Date() })
      .where(eq(projectFile.id, task.fileId));

    void this.fileParseService.runParsePipeline(taskId, task.fileId, fileRows[0].fileUrl).catch(
      (error: unknown) => {
        this.logger.error(
          `retry parse pipeline crashed, taskId=${taskId}: ${JSON.stringify(
            error instanceof Error ? error.message : String(error),
          )}`,
        );
      },
    );

    return { id: taskId, status: 'pending' };
  }
}
