import { Controller, Get, Query } from '@nestjs/common';

import { ProjectService } from './project.service';

@Controller('api/dashboard')
export class DashboardController {
  constructor(private readonly projectService: ProjectService) {}

  @Get('summary')
  async summary() {
    return this.projectService.dashboardSummary();
  }

  @Get('activities')
  async activities(@Query('limit') limit?: string) {
    const parsed = limit ? Math.min(Number(limit) || 20, 100) : 20;
    return this.projectService.dashboardActivities(parsed);
  }
}
