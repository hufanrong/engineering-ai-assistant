import { Module } from '@nestjs/common';

import { ApprovalModule } from '@server/modules/approval/approval.module';
import { RecordController } from './record.controller';
import { RecordService } from './record.service';
import { TypeRecognitionService } from './type-recognition.service';
import { CompletenessService } from './completeness.service';

@Module({
  imports: [ApprovalModule],
  controllers: [RecordController],
  providers: [RecordService, TypeRecognitionService, CompletenessService],
})
export class RecordModule {}
