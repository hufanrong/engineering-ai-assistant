import { Controller, Get, Param, Query } from '@nestjs/common';

import { GraphService } from './graph.service';

function parseEntityTypes(entityTypes?: string): string[] | undefined {
  if (!entityTypes) return undefined;
  const parsed = entityTypes
    .split(',')
    .map((item: string) => item.trim())
    .filter((item: string) => item.length > 0);
  return Array.from(new Set(parsed));
}

@Controller('api')
export class GraphController {
  constructor(private readonly graphService: GraphService) {}

  @Get('projects/:id/graph')
  async getGraphData(
    @Param('id') id: string,
    @Query('entityTypes') entityTypes?: string,
  ) {
    return this.graphService.getGraphData(id, parseEntityTypes(entityTypes));
  }
}
