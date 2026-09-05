/* 实体 properties jsonb 列的安全读取工具（jsonb 无 $type，读出为 unknown） */

export interface EntityProperties {
  model?: string;
  spec?: string;
  material?: string;
  quantity?: string;
}

const PROPERTY_KEYS: readonly string[] = [
  'model',
  'spec',
  'material',
  'quantity',
];

export function isRecordValue(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function readEntityProperties(value: unknown): EntityProperties {
  if (!isRecordValue(value)) {
    return {};
  }
  const props: EntityProperties = {};
  for (const key of PROPERTY_KEYS) {
    const field = value[key];
    if (typeof field === 'string') {
      props[key as keyof EntityProperties] = field;
    }
  }
  return props;
}
