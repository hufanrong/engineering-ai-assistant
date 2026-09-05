import { Body, Controller, Delete, Get, Param, Post, Query, Req } from '@nestjs/common';
import { NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import { FileService } from './file.service';
import { FileTaskService } from './file-task.service';
import { extractUserContext } from '../approval/user-context';
import type { CreateFileRequest } from '@shared/api.interface';

@Controller('api')
export class FileController {
  constructor(
    private readonly fileService: FileService,
    private readonly fileTaskService: FileTaskService,
  ) {}

  @NeedLogin()
  @Post('projects/:id/files')
  async createFile(
    @Param('id') id: string,
    @Body() dto: CreateFileRequest,
    @Req() req: Request,
  ) {
    const { userId } = req.userContext;
    return this.fileService.createFile(id, dto, userId);
  }

  @Get('projects/:id/files')
  async listFiles(
    @Param('id') id: string,
    @Query('workshopId') workshopId?: string,
    @Query('fileType') fileType?: string,
    @Query('parseStatus') parseStatus?: string,
    @Query('keyword') keyword?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.fileService.listFiles(id, {
      workshopId,
      fileType,
      parseStatus,
      keyword,
      offset: offset ? Math.max(Number(offset) || 0, 0) : 0,
      limit: Math.min(Math.max(Number(limit) || 20, 1), 100),
    });
  }

  @Get('files/:id')
  async getFileDetail(@Param('id') id: string) {
    return this.fileService.getFileDetail(id);
  }

  @NeedLogin()
  @Delete('files/:id')
  async deleteFile(@Param('id') id: string, @Req() req: Request) {
    const userContext = extractUserContext(req);
    return this.fileService.deleteFileWithApproval(id, userContext);
  }

  @Get('projects/:id/tasks')
  async listTasks(
    @Param('id') id: string,
    @Query('status') status?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.fileTaskService.listTasks(
      id,
      status,
      offset ? Math.max(Number(offset) || 0, 0) : 0,
      Math.min(Math.max(Number(limit) || 20, 1), 100),
    );
  }

  @NeedLogin()
  @Post('tasks/:id/retry')
  async retryTask(@Param('id') id: string) {
    return this.fileTaskService.retryTask(id);
  }
}
