import { Body, Controller, Delete, Get, Logger, Param, Post, Query, Req } from '@nestjs/common';
import { NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import { extractUserContext } from '../approval/user-context';
import type {
  AddAliasRequest,
  BatchMergeDecisionRequest,
  MergeDecisionRequest,
  ResolveConflictRequest,
} from '@shared/api.interface';
import { EntityDecisionService } from './entity-decision.service';
import { EntityQueueService } from './entity-queue.service';
import { EntityService } from './entity.service';

function parseOffset(offset?: string): number {
  return offset ? Math.max(Number(offset) || 0, 0) : 0;
}

function parseLimit(limit?: string): number {
  return Math.min(Math.max(Number(limit) || 20, 1), 100);
}

@Controller('api')
export class EntityController {
  private readonly logger = new Logger(EntityController.name);

  constructor(
    private readonly entityService: EntityService,
    private readonly entityQueueService: EntityQueueService,
    private readonly entityDecisionService: EntityDecisionService,
  ) {}

  @Get('projects/:id/entities')
  async listEntities(
    @Param('id') id: string,
    @Query('entityType') entityType?: string,
    @Query('workshopId') workshopId?: string,
    @Query('keyword') keyword?: string,
    @Query('mergeStatus') mergeStatus?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.entityService.listEntities(id, {
      entityType,
      workshopId,
      keyword,
      mergeStatus,
      offset: parseOffset(offset),
      limit: parseLimit(limit),
    });
  }

  @Get('entities/:id')
  async getEntityDetail(@Param('id') id: string) {
    return this.entityService.getEntityDetail(id);
  }

  @NeedLogin()
  @Delete('entities/:id')
  async deleteEntity(@Param('id') id: string, @Req() req: Request) {
    const userContext = extractUserContext(req);
    this.logger.log(`delete entity=${id} by=${userContext.userId}`);
    return this.entityDecisionService.deleteEntityWithApproval(id, userContext);
  }

  @NeedLogin()
  @Post('entities/:id/aliases')
  async addAlias(
    @Param('id') id: string,
    @Body() dto: AddAliasRequest,
    @Req() req: Request,
  ) {
    const { userId } = req.userContext;
    this.logger.log(`addAlias entity=${id} by=${userId}`);
    return this.entityDecisionService.addAlias(id, dto);
  }

  @Get('projects/:id/merge-queue')
  async listMergeQueue(
    @Param('id') id: string,
    @Query('status') status?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.entityQueueService.listMergeQueue(
      id,
      status || 'pending',
      parseOffset(offset),
      parseLimit(limit),
    );
  }

  @NeedLogin()
  @Post('merge-queue/batch-decision')
  async batchDecision(@Body() dto: BatchMergeDecisionRequest, @Req() req: Request) {
    const userContext = extractUserContext(req);
    this.logger.log(
      `merge-queue batch-decision count=${dto.ids.length} decision=${dto.decision} by=${userContext.userId}`,
    );
    return this.entityDecisionService.batchDecision(dto.ids, dto.decision, userContext);
  }

  @NeedLogin()
  @Post('merge-queue/:id/decision')
  async decisionMerge(
    @Param('id') id: string,
    @Body() dto: MergeDecisionRequest,
    @Req() req: Request,
  ) {
    const { userId } = req.userContext;
    this.logger.log(
      `merge-queue decision id=${id} decision=${dto.decision} by=${userId}`,
    );
    return this.entityDecisionService.decisionMerge(
      id,
      dto.decision,
      extractUserContext(req),
    );
  }

  @Get('projects/:id/conflicts')
  async listConflicts(
    @Param('id') id: string,
    @Query('status') status?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.entityQueueService.listConflicts(
      id,
      status || 'pending',
      parseOffset(offset),
      parseLimit(limit),
    );
  }

  @NeedLogin()
  @Post('conflicts/:id/resolve')
  async resolveConflict(
    @Param('id') id: string,
    @Body() dto: ResolveConflictRequest,
    @Req() req: Request,
  ) {
    const { userId } = req.userContext;
    this.logger.log(
      `conflict resolve id=${id} resolution=${dto.resolution} by=${userId}`,
    );
    return this.entityDecisionService.resolveConflict(
      id,
      dto,
      extractUserContext(req),
    );
  }

  @Get('projects/:id/pending-counts')
  async getPendingCounts(@Param('id') id: string) {
    return this.entityQueueService.getPendingCounts(id);
  }
}
