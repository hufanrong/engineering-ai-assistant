import { Module } from '@nestjs/common';

import { RagSearchService } from './rag-search.service';
import { RepositoryController } from './repository.controller';
import { RepositoryService } from './repository.service';

@Module({
  controllers: [RepositoryController],
  providers: [RepositoryService, RagSearchService],
})
export class RepositoryModule {}
