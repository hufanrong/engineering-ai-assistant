import { Injectable, Logger } from '@nestjs/common';

import type { RecordField } from '@shared/api.interface';

import { TypeRecognitionService } from './type-recognition.service';

export interface CompletenessResult {
  completeness: number;
  missingFields: RecordField[];
}

@Injectable()
export class CompletenessService {
  private readonly logger = new Logger(CompletenessService.name);

  constructor(private readonly typeRecognitionService: TypeRecognitionService) {}

  /**
   * 按 record_type_config.requiredFields 逐项检查 content：
   * 字段 label（或 key、去空格 label）出现在 content 中视为已提供。
   * 全命中 = 100；无 requiredFields 视为 100。任何情况不抛错。
   */
  async check(recordType: string, content: string): Promise<CompletenessResult> {
    try {
      const config = await this.typeRecognitionService.getConfigByType(recordType);
      const requiredFields = config?.requiredFields ?? [];
      if (requiredFields.length === 0) {
        return { completeness: 100, missingFields: [] };
      }

      const text = content ?? '';
      const missingFields: RecordField[] = [];
      for (const field of requiredFields) {
        if (!field || typeof field.label !== 'string') {
          continue;
        }
        const provided =
          (field.label.length > 0 && text.includes(field.label)) ||
          (typeof field.key === 'string' && field.key.length > 0 && text.includes(field.key)) ||
          text.includes(field.label.replace(/\s+/g, ''));
        if (!provided) {
          missingFields.push({ key: field.key, label: field.label });
        }
      }

      const completeness = Math.round(
        ((requiredFields.length - missingFields.length) / requiredFields.length) * 100,
      );
      return { completeness, missingFields };
    } catch (error) {
      this.logger.warn(
        `completeness check failed: ${error instanceof Error ? error.message : 'unknown'}`,
      );
      return { completeness: 0, missingFields: [] };
    }
  }
}
