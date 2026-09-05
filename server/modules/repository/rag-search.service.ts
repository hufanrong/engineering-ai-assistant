import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import {
  CapabilityService,
  DRIZZLE_DATABASE,
  PostgresJsDatabase,
} from '@lark-apaas/fullstack-nestjs-core';
import { and, desc, eq, ilike, inArray, or } from 'drizzle-orm';

import {
  entity,
  entityAlias,
  fileWorkshop,
  platformMaterial,
  platformStandard,
  project,
  projectFile,
  siteRecord,
  workshop,
} from '@server/database/schema';
import type {
  RagDocumentResult,
  RagEntityResult,
  RagPlatformResult,
  RagSearchRequest,
  RagSearchResponse,
} from '@shared/api.interface';

const SEARCH_SUMMARY_PLUGIN_ID = 'engineering_database_agent_search_summary_1';
const SEARCH_SUMMARY_TIMEOUT_MS = 30000;
const RESULT_LIMIT = 20;
const PLATFORM_RESULT_LIMIT = 10;
const PLATFORM_EXTRA_MAX_LENGTH = 120;
const NO_RESULT_SUMMARY = '未检索到相关内容';
const HIGHLIGHTS_MAX_LENGTH = 2000;

type SummaryChunk = { summary?: unknown };

@Injectable()
export class RagSearchService {
  private readonly logger = new Logger(RagSearchService.name);

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
    private readonly capabilityService: CapabilityService,
  ) {}

  async search(
    request: RagSearchRequest,
    agentApiKey: string | undefined,
  ): Promise<RagSearchResponse> {
    await this.authenticate(request.projectId, agentApiKey);

    const query = (request.query ?? '').trim();
    if (query === '') {
      return {
        documentResults: [],
        entityResults: [],
        platformResults: [],
        summary: NO_RESULT_SUMMARY,
      };
    }

    const pattern = `%${query}%`;
    const workshopId = request.workshopId ?? undefined;

    const [recordDocs, fileDocs, entityResults, platformResults] =
      await Promise.all([
        this.searchRecords(request.projectId, pattern, workshopId),
        this.searchFiles(request.projectId, pattern, workshopId),
        this.searchEntities(request.projectId, pattern, workshopId),
        this.searchPlatformLibs(pattern),
      ]);

    const documentResults: RagDocumentResult[] = [...recordDocs, ...fileDocs]
      .sort((a: RagDocumentResult, b: RagDocumentResult) =>
        b.createdAt.localeCompare(a.createdAt),
      )
      .slice(0, RESULT_LIMIT * 2);

    const hasHits =
      documentResults.length > 0 ||
      entityResults.length > 0 ||
      platformResults.length > 0;
    let summary = '';
    if (hasHits) {
      const highlights = this.buildHighlights(
        documentResults,
        entityResults,
        platformResults,
      );
      try {
        summary = await this.summarize(query, highlights);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        this.logger.warn(
          `summary plugin failed, projectId=${request.projectId}: ${message}`,
        );
        summary = '';
      }
    } else {
      summary = NO_RESULT_SUMMARY;
    }

    return { documentResults, entityResults, platformResults, summary };
  }

  private async authenticate(
    projectId: string,
    agentApiKey: string | undefined,
  ): Promise<void> {
    const projectRows = await this.db
      .select({ agentApiKey: project.agentApiKey })
      .from(project)
      .where(eq(project.id, projectId))
      .limit(1);
    if (
      projectRows.length === 0 ||
      agentApiKey === undefined ||
      agentApiKey === '' ||
      agentApiKey !== projectRows[0].agentApiKey
    ) {
      throw new UnauthorizedException('无效的 Agent API Key');
    }
  }

  private async searchRecords(
    projectId: string,
    pattern: string,
    workshopId: string | undefined,
  ): Promise<RagDocumentResult[]> {
    const conditions = [
      eq(siteRecord.projectId, projectId),
      or(ilike(siteRecord.title, pattern), ilike(siteRecord.content, pattern)),
    ];
    if (workshopId !== undefined) {
      conditions.push(eq(siteRecord.workshopId, workshopId));
    }

    const rows = await this.db
      .select({
        title: siteRecord.title,
        content: siteRecord.content,
        recordType: siteRecord.recordType,
        workshopName: workshop.name,
        createdAt: siteRecord.createdAt,
      })
      .from(siteRecord)
      .leftJoin(workshop, eq(siteRecord.workshopId, workshop.id))
      .where(and(...conditions))
      .orderBy(desc(siteRecord.createdAt))
      .limit(RESULT_LIMIT);

    return rows.map((row) => {
      const content = row.content ?? '';
      const title =
        row.title && row.title.trim() !== ''
          ? row.title
          : content.slice(0, 50) || '未命名记录';
      return {
        sourceType: 'record' as const,
        title,
        content: content.slice(0, 500),
        recordType: row.recordType,
        workshopName: row.workshopName ?? undefined,
        createdAt: row.createdAt.toISOString(),
      };
    });
  }

  private async searchFiles(
    projectId: string,
    pattern: string,
    workshopId: string | undefined,
  ): Promise<RagDocumentResult[]> {
    const conditions = [
      eq(projectFile.projectId, projectId),
      ilike(projectFile.filename, pattern),
    ];
    if (workshopId !== undefined) {
      conditions.push(
        inArray(
          projectFile.id,
          this.db
            .select({ id: fileWorkshop.fileId })
            .from(fileWorkshop)
            .where(eq(fileWorkshop.workshopId, workshopId)),
        ),
      );
    }

    const rows = await this.db
      .select({
        filename: projectFile.filename,
        fileType: projectFile.fileType,
        versionNo: projectFile.versionNo,
        createdAt: projectFile.createdAt,
      })
      .from(projectFile)
      .where(and(...conditions))
      .orderBy(desc(projectFile.createdAt))
      .limit(RESULT_LIMIT);

    return rows.map((row) => ({
      sourceType: 'file' as const,
      title: row.filename,
      content: `文件（类型 ${row.fileType}，版本 ${row.versionNo}）`,
      createdAt: row.createdAt.toISOString(),
    }));
  }

  private async searchEntities(
    projectId: string,
    pattern: string,
    workshopId: string | undefined,
  ): Promise<RagEntityResult[]> {
    const baseConditions = [eq(entity.projectId, projectId)];
    if (workshopId !== undefined) {
      baseConditions.push(eq(entity.workshopId, workshopId));
    }

    const nameMatched = await this.db
      .select()
      .from(entity)
      .where(
        and(
          ...baseConditions,
          or(ilike(entity.name, pattern), ilike(entity.code, pattern)),
        ),
      )
      .limit(RESULT_LIMIT);

    const aliasMatched = await this.db
      .select()
      .from(entity)
      .where(
        and(
          ...baseConditions,
          inArray(
            entity.id,
            this.db
              .select({ id: entityAlias.entityId })
              .from(entityAlias)
              .where(
                or(
                  ilike(entityAlias.aliasName, pattern),
                  ilike(entityAlias.aliasCode, pattern),
                ),
              ),
          ),
        ),
      )
      .limit(RESULT_LIMIT);

    const merged = new Map<string, typeof entity.$inferSelect>();
    for (const row of [...nameMatched, ...aliasMatched]) {
      if (!merged.has(row.id)) {
        merged.set(row.id, row);
      }
    }
    const entityRows = [...merged.values()].slice(0, RESULT_LIMIT);
    if (entityRows.length === 0) {
      return [];
    }

    const entityIds = entityRows.map((row) => row.id);
    const aliasRows = await this.db
      .select({
        entityId: entityAlias.entityId,
        aliasName: entityAlias.aliasName,
        aliasCode: entityAlias.aliasCode,
      })
      .from(entityAlias)
      .where(inArray(entityAlias.entityId, entityIds));

    const aliasMap = new Map<string, string[]>();
    for (const row of aliasRows) {
      const values = [row.aliasName, row.aliasCode].filter(
        (value: string | null): value is string =>
          value !== null && value.trim() !== '',
      );
      aliasMap.set(row.entityId, [...(aliasMap.get(row.entityId) ?? []), ...values]);
    }

    return entityRows.map((row) => ({
      id: row.id,
      name: row.name,
      code: row.code,
      entityType: row.entityType,
      aliases: [
        ...new Set(
          [row.name, row.code, ...(aliasMap.get(row.id) ?? [])].filter(
            (value: string | null): value is string =>
              value !== null && value.trim() !== '',
          ),
        ),
      ],
    }));
  }

  private async searchPlatformLibs(
    pattern: string,
  ): Promise<RagPlatformResult[]> {
    const [standardRows, materialRows] = await Promise.all([
      this.db
        .select({
          id: platformStandard.id,
          name: platformStandard.name,
          standardCode: platformStandard.standardCode,
          category: platformStandard.category,
          content: platformStandard.content,
        })
        .from(platformStandard)
        .where(
          or(
            ilike(platformStandard.name, pattern),
            ilike(platformStandard.standardCode, pattern),
            ilike(platformStandard.category, pattern),
            ilike(platformStandard.content, pattern),
          ),
        )
        .limit(PLATFORM_RESULT_LIMIT),
      this.db
        .select({
          id: platformMaterial.id,
          name: platformMaterial.name,
          standardCode: platformMaterial.standardCode,
          materialGrade: platformMaterial.materialGrade,
          spec: platformMaterial.spec,
        })
        .from(platformMaterial)
        .where(
          or(
            ilike(platformMaterial.name, pattern),
            ilike(platformMaterial.materialGrade, pattern),
            ilike(platformMaterial.spec, pattern),
            ilike(platformMaterial.standardCode, pattern),
          ),
        )
        .limit(PLATFORM_RESULT_LIMIT),
    ]);

    const standardResults: RagPlatformResult[] = standardRows.map((row) => ({
      id: row.id,
      libType: 'standard' as const,
      name: row.name,
      code: row.standardCode,
      extra:
        (row.content ?? '').trim() !== ''
          ? (row.content ?? '').slice(0, PLATFORM_EXTRA_MAX_LENGTH)
          : row.category ?? undefined,
    }));

    const materialResults: RagPlatformResult[] = materialRows.map((row) => ({
      id: row.id,
      libType: 'material' as const,
      name: row.name,
      code: row.standardCode ?? undefined,
      extra:
        [row.materialGrade, row.spec]
          .filter(
            (value: string | null): value is string =>
              value !== null && value.trim() !== '',
          )
          .join(' / ') || undefined,
    }));

    return [...standardResults, ...materialResults];
  }

  private buildHighlights(
    documentResults: RagDocumentResult[],
    entityResults: RagEntityResult[],
    platformResults: RagPlatformResult[],
  ): string {
    const parts = [
      ...documentResults.map(
        (doc: RagDocumentResult) => `${doc.title}: ${doc.content}`,
      ),
      ...entityResults.map(
        (item: RagEntityResult) => `实体 ${item.name}（${item.entityType}）`,
      ),
      ...platformResults.map(
        (item: RagPlatformResult) =>
          `平台${item.libType === 'standard' ? '规范' : '材料'} ${item.name}` +
          `${item.code ? `（${item.code}）` : ''}` +
          `${item.extra ? `: ${item.extra}` : ''}`,
      ),
    ];
    return parts.join('\n').slice(0, HIGHLIGHTS_MAX_LENGTH);
  }

  private async summarize(
    searchQuery: string,
    highlights: string,
  ): Promise<string> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(
        () => reject(new Error('summary plugin timeout')),
        SEARCH_SUMMARY_TIMEOUT_MS,
      );
    });
    try {
      return await Promise.race([
        this.callSummaryPlugin(searchQuery, highlights),
        timeout,
      ]);
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    }
  }

  private async callSummaryPlugin(
    searchQuery: string,
    highlights: string,
  ): Promise<string> {
    const response: unknown = await this.capabilityService
      .load(SEARCH_SUMMARY_PLUGIN_ID)
      .callStream('searchSummary', {
        search_query: searchQuery,
        content_highlights: highlights,
      });
    const stream = this.resolveStream(response);
    let summary = '';
    for await (const chunk of stream) {
      summary += typeof chunk.summary === 'string' ? chunk.summary : '';
    }
    return summary;
  }

  private resolveStream(response: unknown): AsyncIterable<SummaryChunk> {
    if (this.isAsyncIterable(response)) {
      return response;
    }
    if (response !== null && typeof response === 'object') {
      const output: unknown = (response as { output?: unknown }).output;
      if (this.isAsyncIterable(output)) {
        return output;
      }
    }
    throw new Error('unexpected summary stream shape');
  }

  private isAsyncIterable(
    value: unknown,
  ): value is AsyncIterable<SummaryChunk> {
    if (value === null || typeof value !== 'object') {
      return false;
    }
    const iterator = (value as { [Symbol.asyncIterator]?: unknown })[
      Symbol.asyncIterator
    ];
    return typeof iterator === 'function';
  }
}
