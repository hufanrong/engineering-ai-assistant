import {
  Body,
  Controller,
  Get,
  Headers,
  Param,
  Post,
  Req,
} from '@nestjs/common';
import type { Request } from 'express';

import { RagSearchService } from './rag-search.service';
import { RepositoryService } from './repository.service';
import type {
  RagSearchRequest,
  RagSearchResponse,
  RepositoryInfo,
  RotateKeyResponse,
} from '@shared/api.interface';

const DEFAULT_APP_ID = 'app_17dfhhexbzp';
const APP_ID_PATTERN = /\/app\/(app_[a-z0-9]+)\//;

@Controller('api')
export class RepositoryController {
  constructor(
    private readonly repositoryService: RepositoryService,
    private readonly ragSearchService: RagSearchService,
  ) {}

  @Get('projects/:id/repository-info')
  async getRepositoryInfo(
    @Req() req: Request,
    @Param('id') projectId: string,
  ): Promise<RepositoryInfo> {
    return this.repositoryService.getRepositoryInfo(
      projectId,
      this.resolveAppId(req),
    );
  }

  @Post('projects/:id/api-keys/rotate')
  async rotateKey(@Param('id') projectId: string): Promise<RotateKeyResponse> {
    return this.repositoryService.rotateKey(projectId);
  }

  @Post('rag/search')
  async search(
    @Headers('x-agent-api-key') agentApiKey: string | undefined,
    @Body() body: RagSearchRequest,
  ): Promise<RagSearchResponse> {
    return this.ragSearchService.search(body, agentApiKey);
  }

  private resolveAppId(req: Request): string {
    const url: string =
      typeof req.originalUrl === 'string' ? req.originalUrl : '';
    const match = APP_ID_PATTERN.exec(url);
    return match !== null ? match[1] : DEFAULT_APP_ID;
  }
}
