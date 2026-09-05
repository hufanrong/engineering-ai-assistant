import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  Post,
  Put,
  Query,
} from '@nestjs/common';
import { NeedLogin } from '@lark-apaas/fullstack-nestjs-core';

import type {
  CreatePlatformMaterialRequest,
  CreatePlatformProcessRequest,
  CreatePlatformStandardRequest,
  UpdatePlatformMaterialRequest,
  UpdatePlatformProcessRequest,
  UpdatePlatformStandardRequest,
} from '@shared/api.interface';
import { PlatformDataService } from './platform-data.service';

function parseOffset(offset?: string): number {
  return offset ? Math.max(Number(offset) || 0, 0) : 0;
}

function parseLimit(limit?: string): number {
  return Math.min(Math.max(Number(limit) || 20, 1), 100);
}

@Controller('api/platform')
export class PlatformDataController {
  constructor(private readonly platformDataService: PlatformDataService) {}

  // ---------- 规范库 ----------

  @Get('standards')
  async listStandards(
    @Query('keyword') keyword?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.platformDataService.listStandards(
      keyword,
      parseOffset(offset),
      parseLimit(limit),
    );
  }

  @NeedLogin()
  @Post('standards')
  async createStandard(@Body() dto: CreatePlatformStandardRequest) {
    return this.platformDataService.createStandard(dto);
  }

  @NeedLogin()
  @Put('standards/:id')
  async updateStandard(
    @Param('id') id: string,
    @Body() dto: UpdatePlatformStandardRequest,
  ) {
    return this.platformDataService.updateStandard(id, dto);
  }

  @NeedLogin()
  @Delete('standards/:id')
  async deleteStandard(@Param('id') id: string) {
    return this.platformDataService.deleteStandard(id);
  }

  // ---------- 材料库 ----------

  @Get('materials')
  async listMaterials(
    @Query('keyword') keyword?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.platformDataService.listMaterials(
      keyword,
      parseOffset(offset),
      parseLimit(limit),
    );
  }

  @NeedLogin()
  @Post('materials')
  async createMaterial(@Body() dto: CreatePlatformMaterialRequest) {
    return this.platformDataService.createMaterial(dto);
  }

  @NeedLogin()
  @Put('materials/:id')
  async updateMaterial(
    @Param('id') id: string,
    @Body() dto: UpdatePlatformMaterialRequest,
  ) {
    return this.platformDataService.updateMaterial(id, dto);
  }

  @NeedLogin()
  @Delete('materials/:id')
  async deleteMaterial(@Param('id') id: string) {
    return this.platformDataService.deleteMaterial(id);
  }

  // ---------- 工艺库 ----------

  @Get('processes')
  async listProcesses(
    @Query('keyword') keyword?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ) {
    return this.platformDataService.listProcesses(
      keyword,
      parseOffset(offset),
      parseLimit(limit),
    );
  }

  @NeedLogin()
  @Post('processes')
  async createProcess(@Body() dto: CreatePlatformProcessRequest) {
    return this.platformDataService.createProcess(dto);
  }

  @NeedLogin()
  @Put('processes/:id')
  async updateProcess(
    @Param('id') id: string,
    @Body() dto: UpdatePlatformProcessRequest,
  ) {
    return this.platformDataService.updateProcess(id, dto);
  }

  @NeedLogin()
  @Delete('processes/:id')
  async deleteProcess(@Param('id') id: string) {
    return this.platformDataService.deleteProcess(id);
  }
}
