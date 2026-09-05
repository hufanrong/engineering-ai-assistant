import { Inject, Injectable, Logger } from '@nestjs/common';
import { asc, eq } from 'drizzle-orm';

import { DRIZZLE_DATABASE, type PostgresJsDatabase } from '@lark-apaas/fullstack-nestjs-core';

import { recordTypeConfig } from '@server/database/schema';

interface RecordTypeConfigRow {
  recordType: string;
  displayName: string;
  category: string;
  requiredFields: Array<{ key: string; label: string }> | null;
  keywords: string[] | null;
}

export interface TypeRecognitionResult {
  recordType: string;
  confidence: number;
  matchedCount: number;
  highConfidence: boolean;
}

@Injectable()
export class TypeRecognitionService {
  private readonly logger = new Logger(TypeRecognitionService.name);

  private configCache: RecordTypeConfigRow[] | null = null;

  constructor(
    @Inject(DRIZZLE_DATABASE) private readonly db: PostgresJsDatabase,
  ) {}

  async getConfigs(): Promise<RecordTypeConfigRow[]> {
    if (this.configCache) {
      return this.configCache;
    }
    const rows = await this.db
      .select({
        recordType: recordTypeConfig.recordType,
        displayName: recordTypeConfig.displayName,
        category: recordTypeConfig.category,
        requiredFields: recordTypeConfig.requiredFields,
        keywords: recordTypeConfig.keywords,
      })
      .from(recordTypeConfig)
      .where(eq(recordTypeConfig.enabled, true))
      .orderBy(asc(recordTypeConfig.sortOrder));
    const configs: RecordTypeConfigRow[] = rows.map((row) => ({
      recordType: row.recordType,
      displayName: row.displayName,
      category: row.category,
      requiredFields: Array.isArray(row.requiredFields)
        ? (row.requiredFields as Array<{ key: string; label: string }>)
        : [],
      keywords: Array.isArray(row.keywords) ? (row.keywords as string[]) : [],
    }));
    this.configCache = configs;
    return configs;
  }

  invalidateCache(): void {
    this.configCache = null;
  }

  async getConfigByType(recordType: string): Promise<RecordTypeConfigRow | undefined> {
    const configs = await this.getConfigs();
    return configs.find((c) => c.recordType === recordType);
  }

  /**
   * 对输入文本做关键词匹配，任何情况不抛错。
   * 置信度 = 命中数 / 该类型关键词总数（上限 1）。
   * 高置信（自动设定类型）：置信度 >= 0.15 或命中数 >= 2。
   * 中置信（命中数 1）：设定最可能类型但由调用方记录置 pending_classify。
   */
  async recognize(text: string): Promise<TypeRecognitionResult> {
    const empty: TypeRecognitionResult = {
      recordType: 'other',
      confidence: 0,
      matchedCount: 0,
      highConfidence: false,
    };
    try {
      const configs = await this.getConfigs();
      const content = (text ?? '').toLowerCase();
      if (!content) {
        return empty;
      }

      let best: TypeRecognitionResult = empty;
      for (const config of configs) {
        const keywords = Array.isArray(config.keywords) ? config.keywords : [];
        if (keywords.length === 0) {
          continue;
        }
        const matchedCount = keywords.filter(
          (kw: string) => typeof kw === 'string' && kw.length > 0 && content.includes(kw.toLowerCase()),
        ).length;
        if (matchedCount === 0) {
          continue;
        }
        const confidence = Math.min(matchedCount / keywords.length, 1);
        const highConfidence = confidence >= 0.15 || matchedCount >= 2;
        if (
          matchedCount > best.matchedCount ||
          (matchedCount === best.matchedCount && confidence > best.confidence)
        ) {
          best = { recordType: config.recordType, confidence, matchedCount, highConfidence };
        }
      }
      return best;
    } catch (error) {
      this.logger.warn(
        `type recognition failed: ${error instanceof Error ? error.message : 'unknown'}`,
      );
      return empty;
    }
  }
}
