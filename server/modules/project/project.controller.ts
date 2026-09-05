import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  Post,
  Put,
  Query,
  Req,
} from '@nestjs/common';
import { CanRole, NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import { ProjectService } from './project.service';
import type {
  CreateProjectRequest,
  CreateWorkshopRequest,
  UpdateProjectRequest,
} from '@shared/api.interface';

@Controller('api/projects')
export class ProjectController {
  constructor(private readonly projectService: ProjectService) {}

  @Get('module-status')
  getModuleStatus() {
    return this.projectService.getModuleStatus();
  }

  @Get()
  async list(
    @Query('keyword') keyword?: string,
    @Query('status') status?: string,
  ) {
    return this.projectService.listProjects(keyword, status);
  }

  @NeedLogin()
  @CanRole(['super_admin', 'admin'])
  @Post()
  async create(@Body() dto: CreateProjectRequest) {
    return this.projectService.createProject(dto);
  }

  @Get(':id')
  async detail(@Param('id') id: string) {
    return this.projectService.getProjectDetail(id);
  }

  @Get(':id/statistics')
  async statistics(@Param('id') id: string) {
    return this.projectService.getStatistics(id);
  }

  @Get(':id/workshops')
  async listWorkshops(@Param('id') id: string) {
    return this.projectService.listWorkshops(id);
  }

  @NeedLogin()
  @Post(':id/workshops')
  async createWorkshop(@Param('id') id: string, @Body() dto: CreateWorkshopRequest) {
    return this.projectService.createWorkshop(id, dto);
  }

  @NeedLogin()
  @CanRole(['super_admin', 'admin'])
  @Put(':id')
  async updateProject(@Param('id') id: string, @Body() dto: UpdateProjectRequest) {
    return this.projectService.updateProject(id, dto);
  }

  @NeedLogin()
  @CanRole(['super_admin', 'admin'])
  @Delete(':id')
  async deleteProject(@Param('id') id: string) {
    return this.projectService.deleteProject(id);
  }
}
