import { Inject, Injectable, Logger } from '@nestjs/common';import {
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
  CapabilityService,
} from '@lark-apaas/fullstack-nestjs-core';
import { eq } from 'drizzle-orm';

import { backgroundTask, fileWorkshop, projectFile } from '@server/database/schema';
import { EntityMergeService } from '@server/modules/entity/entity-merge.service';
import type { ExtractedEntity } from '@server/modules/entity/entity-merge.service';

const DOC_PARSER_PLUGIN_ID = 'engineering_document_parser_1';
const ENTITY_EXTRACT_PLUGIN_ID = 'engineering_ledger_entity_extraction_1';

export const PARSEABLE_FILE_TYPES = ['pdf', 'docx', 'xlsx', 'txt', 'dwg', 'chat'];

export function isParseableFileType(fileType: string): boolean {
  return PARSEABLE_FILE_TYPES.includes(fileType);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readStringField(value: unknown, key: string): string {
  if (isRecord(value)) {
    const field = value[key];
    if (typeof field === 'string') {
      return field;
    }
  }
  return '';
}

@Injectable()
export class FileParseService {
  private readonly logger = new Logger(FileParseService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly capabilityService: CapabilityService,
    private readonly entityMergeService: EntityMergeService,
  ) {}

  async runParsePipeline(taskId: string, fileId: string, fileUrl: string): Promise<void> {
    try {
      await this.db
        .update(backgroundTask)
        .set({ status: 'running', progress: 5, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));
      await this.db
        .update(projectFile)
        .set({ parseStatus: 'processing', parseError: null, updatedAt: new Date() })
        .where(eq(projectFile.id, fileId));

      const parsed = await this.capabilityService
        .load(DOC_PARSER_PLUGIN_ID)
        .call('parseDocToMarkdown', { fileUrl: [fileUrl] });
      const markdown = readStringField(parsed, 'content');

      await this.db
        .update(backgroundTask)
        .set({ progress: 40, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));

      const extracted = await this.capabilityService
        .load(ENTITY_EXTRACT_PLUGIN_ID)
        .call('textToJson', { text: markdown });
      const entityText = readStringField(extracted, 'entities') || '[]';

      await this.db
        .update(backgroundTask)
        .set({ progress: 70, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));

      const fileRow = await this.db
        .select({ projectId: projectFile.projectId })
        .from(projectFile)
        .where(eq(projectFile.id, fileId))
        .limit(1);
      if (fileRow.length === 0) {
        throw new Error(`文件不存在: ${fileId}`);
      }
      const workshopRow = await this.db
        .select({ workshopId: fileWorkshop.workshopId })
        .from(fileWorkshop)
        .where(eq(fileWorkshop.fileId, fileId))
        .limit(1);

      let entities: ExtractedEntity[] = [];
      try {
        const parsedEntities: unknown = JSON.parse(entityText);
        if (Array.isArray(parsedEntities)) {
          entities = parsedEntities as ExtractedEntity[];
        }
      } catch (error) {
        this.logger.warn(
          `entities JSON parse failed, taskId=${taskId}: ${JSON.stringify(
            error instanceof Error ? error.message : String(error),
          )}`,
        );
      }

      const validEntities = entities.filter((item: ExtractedEntity) => Boolean(item?.name));
      if (validEntities.length > 0) {
        await this.entityMergeService.ingestEntities(
          fileRow[0].projectId,
          workshopRow.length > 0 ? workshopRow[0].workshopId : null,
          fileId,
          'manufacturer',
          validEntities,
        );
      }

      await this.db
        .update(backgroundTask)
        .set({ status: 'success', progress: 100, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));
      await this.db
        .update(projectFile)
        .set({ parseStatus: 'success', parseError: null, updatedAt: new Date() })
        .where(eq(projectFile.id, fileId));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.logger.error(
        JSON.stringify({
          pluginInstanceId: `${DOC_PARSER_PLUGIN_ID}/${ENTITY_EXTRACT_PLUGIN_ID}`,
          actionKey: 'parseDocToMarkdown/textToJson',
          outputMode: 'unary',
          taskId,
          fileId,
          error: message,
        }),
      );
      await this.db
        .update(backgroundTask)
        .set({ status: 'failed', message, updatedAt: new Date() })
        .where(eq(backgroundTask.id, taskId));
      await this.db
        .update(projectFile)
        .set({ parseStatus: 'failed', parseError: message, updatedAt: new Date() })
        .where(eq(projectFile.id, fileId));
    }
  }
}
