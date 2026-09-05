import { Body, Controller, Delete, Get, Param, Post, Put, Query, Req } from '@nestjs/common';
import { NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import { extractUserContext } from '../approval/user-context';
import { RecordService } from './record.service';
import type { CaptureWithFileDto } from './record.service';
import type {
  CreateRecordRequest,
  SupplementRequest,
  UpdateRecordRequest,
} from '@shared/api.interface';

@Controller('api')
export class RecordController {
  constructor(private readonly recordService: RecordService) {}

  @Get('record-type-configs')
  async listRecordTypeConfigs() {
    return this.recordService.listRecordTypeConfigs();
  }

  @Get('site-records')
  async listRecords(
    @Req() req: Request,
    @Query('projectId') projectId?: string,
    @Query('recordType') recordType?: string,
    @Query('status') status?: string,
    @Query('keyword') keyword?: string,
    @Query('creator') creator?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    const creatorUserId =
      creator === 'me' ? (req.userContext as { userId?: string } | undefined)?.userId : undefined;
    return this.recordService.listRecords({
      projectId,
      recordType,
      status,
      keyword,
      creatorUserId,
      offset: offset ? Number(offset) : 0,
      limit: limit ? Math.min(Number(limit), 100) : 20,
    });
  }

  @Get('site-records/capture-result/:taskId')
  async captureResult(@Param('taskId') taskId: string) {
    return this.recordService.getCaptureResult(taskId);
  }

  @Get('site-records/:id')
  async detail(@Param('id') id: string) {
    return this.recordService.getRecordDetail(id);
  }

  @NeedLogin()
  @Delete('site-records/:id')
  async deleteRecord(@Param('id') id: string, @Req() req: Request) {
    const userContext = extractUserContext(req);
    return this.recordService.deleteRecordWithApproval(id, userContext);
  }

  @NeedLogin()
  @Put('site-records/:id')
  async update(@Param('id') id: string, @Body() dto: UpdateRecordRequest, @Req() req: Request) {
    const userId = (req.userContext as { userId?: string } | undefined)?.userId ?? '';
    return this.recordService.updateRecord(id, dto, userId);
  }

  @NeedLogin()
  @Post('site-records/:id/supplement')
  async supplement(@Param('id') id: string, @Body() dto: SupplementRequest, @Req() req: Request) {
    const userId = (req.userContext as { userId?: string } | undefined)?.userId ?? '';
    return this.recordService.supplementRecord(id, dto, userId);
  }

  @NeedLogin()
  @Post('site-records')
  async create(@Body() dto: CreateRecordRequest, @Req() req: Request) {
    const userId = (req.userContext as { userId?: string } | undefined)?.userId ?? '';
    return this.recordService.createRecord(dto, userId);
  }

  @NeedLogin()
  @Post('site-records/with-file')
  async captureWithFile(@Body() dto: CaptureWithFileDto, @Req() req: Request) {
    const userId = (req.userContext as { userId?: string } | undefined)?.userId ?? '';
    return this.recordService.captureWithFile(dto, userId);
  }
}
