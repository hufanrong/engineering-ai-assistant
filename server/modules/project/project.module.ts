import { Module } from '@nestjs/common';

import { DashboardController } from './dashboard.controller';
import { ProjectController } from './project.controller';
import { ProjectService } from './project.service';
import { WorkshopController } from './workshop.controller';

@Module({
  controllers: [ProjectController, WorkshopController, DashboardController],
  providers: [ProjectService],
})
export class ProjectModule {}
