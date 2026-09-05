import { Module } from '@nestjs/common';
import { ApprovalModule } from '@server/modules/approval/approval.module';
import { EntityModule } from '@server/modules/entity/entity.module';
import { FileController } from './file.controller';
import { FileParseService } from './file-parse.service';
import { FileService } from './file.service';
import { FileTaskService } from './file-task.service';

@Module({
  imports: [EntityModule, ApprovalModule],
  controllers: [FileController],
  providers: [FileService, FileParseService, FileTaskService],
})
export class FileModule {}
