import { APP_FILTER } from '@nestjs/core';
import { Module } from '@nestjs/common';
import { PlatformModule } from '@lark-apaas/fullstack-nestjs-core';

import { GlobalExceptionFilter } from './common/filters/exception.filter';
import { ViewModule } from './modules/view/view.module';
import { ProjectModule } from './modules/project/project.module';
import { FileModule } from './modules/file/file.module';
import { RecordModule } from './modules/record/record.module';
import { EntityModule } from './modules/entity/entity.module';
import { RepositoryModule } from './modules/repository/repository.module';
import { PlatformDataModule } from './modules/platform/platform-data.module';
import { ApprovalModule } from './modules/approval/approval.module';

@Module({
  imports: [
    // 平台 Module，提供平台能力
    PlatformModule.forRoot(),
    // ====== @route-section: business-modules START ======
    // Place all business modules here.Do NOT add fallback modules here.
    ProjectModule,
    FileModule,
    RecordModule,
    EntityModule,
    RepositoryModule,
    PlatformDataModule,
    ApprovalModule,
    // ====== @route-section: business-modules END ======

    // ⚠️ @route-order: last
    // ViewModule is the fallback route module, must be registered last.
    ViewModule,
  ],
  providers: [
    {
      provide: APP_FILTER,
      useClass: GlobalExceptionFilter,
    },
  ],
})
export class AppModule {}
