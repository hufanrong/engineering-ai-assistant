import { Body, Controller, Delete, Param, Put, Req } from '@nestjs/common';
import { NeedLogin } from '@lark-apaas/fullstack-nestjs-core';
import type { Request } from 'express';

import { ProjectService } from './project.service';
import type { UpdateWorkshopRequest } from '@shared/api.interface';

@Controller('api/workshops')
export class WorkshopController {
  constructor(private readonly projectService: ProjectService) {}

  @NeedLogin()
  @Put(':id')
  async update(@Param('id') id: string, @Req() req: Request, @Body() dto: UpdateWorkshopRequest) {
    const { userId } = req.userContext;
    return this.projectService.updateWorkshop(id, dto, userId ?? '');
  }

  @NeedLogin()
  @Delete(':id')
  async remove(@Param('id') id: string) {
    return this.projectService.deleteWorkshop(id);
  }
}
