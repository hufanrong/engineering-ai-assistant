import {
  Body,
  Controller,
  Get,
  Logger,
  Param,
  Post,
  Query,
  Req,
} from '@nestjs/common';
import { CanRole, NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import type { RejectApprovalRequest } from '@shared/api.interface';
import { ApprovalService } from './approval.service';
import { extractUserContext } from './user-context';

@Controller('api')
export class ApprovalController {
  private readonly logger = new Logger(ApprovalController.name);

  constructor(private readonly approvalService: ApprovalService) {}

  @Get('projects/:id/approvals')
  async listApprovals(
    @Param('id') id: string,
    @Query('status') status?: string,
    @Query('requestType') requestType?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.approvalService.listApprovals(id, {
      status,
      requestType,
      offset: offset ? Math.max(Number(offset) || 0, 0) : 0,
      limit: Math.min(Math.max(Number(limit) || 20, 1), 100),
    });
  }

  @NeedLogin()
  @CanRole(['super_admin'])
  @Post('approvals/:id/approve')
  async approve(@Param('id') id: string, @Req() req: Request) {
    const { userId } = extractUserContext(req);
    this.logger.log(`approve approval=${id} by=${userId}`);
    return this.approvalService.approve(id, userId);
  }

  @NeedLogin()
  @CanRole(['super_admin'])
  @Post('approvals/:id/reject')
  async reject(
    @Param('id') id: string,
    @Body() dto: RejectApprovalRequest,
    @Req() req: Request,
  ) {
    const { userId } = extractUserContext(req);
    this.logger.log(`reject approval=${id} by=${userId} reason=${dto.reason ?? ''}`);
    return this.approvalService.reject(id, userId, dto.reason);
  }
}
