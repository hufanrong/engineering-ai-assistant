import { Module } from '@nestjs/common';
import { PlatformDataController } from './platform-data.controller';
import { PlatformDataService } from './platform-data.service';

@Module({
  controllers: [PlatformDataController],
  providers: [PlatformDataService],
})
export class PlatformDataModule {}
