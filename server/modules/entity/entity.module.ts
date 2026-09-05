import { Module } from '@nestjs/common';
import { ApprovalModule } from '@server/modules/approval/approval.module';
import { EntityController } from './entity.controller';
import { GraphController } from './graph.controller';
import { GraphService } from './graph.service';
import { EntityDecisionService } from './entity-decision.service';
import { EntityMergeService } from './entity-merge.service';
import { EntityQueueService } from './entity-queue.service';
import { EntityService } from './entity.service';

@Module({
  imports: [ApprovalModule],
  controllers: [EntityController, GraphController],
  providers: [EntityService, EntityQueueService, EntityDecisionService, EntityMergeService, GraphService],
  exports: [EntityMergeService, EntityService],
})
export class EntityModule {}
