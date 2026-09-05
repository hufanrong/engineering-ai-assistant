/* 实体相似度计算与候选匹配工具（不引入三方库，基于 Levenshtein 距离） */

import { readEntityProperties } from './entity-property.util';

export interface ExistingEntityRow {
  id: string;
  entityType: string;
  name: string;
  code: string | null;
  workshopId: string | null;
  properties: unknown;
}

export interface CompositeMatch {
  candidate: ExistingEntityRow;
  score: number;
  reason: string;
}

const CODE_SIMILARITY_THRESHOLD = 0.9;
const COMPOSITE_SCORE_THRESHOLD = 0.8;


export function levenshteinDistance(a: string, b: string): number {
  const aChars: string[] = Array.from(a);
  const bChars: string[] = Array.from(b);
  if (aChars.length === 0) return bChars.length;
  if (bChars.length === 0) return aChars.length;
  let prev: number[] = bChars.map((_: string, index: number) => index);
  for (let i = 1; i <= aChars.length; i += 1) {
    const curr: number[] = [i];
    for (let j = 1; j <= bChars.length; j += 1) {
      const cost = aChars[i - 1] === bChars[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
    }
    prev = curr;
  }
  return prev[bChars.length];
}

export function similarity(a: string, b: string): number {
  if (a === b) return 1;
  if (!a || !b) return 0;
  const maxLen = Math.max(Array.from(a).length, Array.from(b).length);
  if (maxLen === 0) return 1;
  return 1 - levenshteinDistance(a, b) / maxLen;
}

export function modelSimilarity(a: string | undefined, b: string | undefined): number {
  const aValue = a ?? '';
  const bValue = b ?? '';
  if (!aValue && !bValue) return 1;
  return similarity(aValue, bValue);
}

/** 编号相似度 > 0.9 且同车间同类型的既有实体 */
export function findSimilarByCode(
  existingRows: ExistingEntityRow[],
  code: string | null,
  workshopId: string | null,
  entityType: string,
): ExistingEntityRow | undefined {
  if (!code) return undefined;
  let best: ExistingEntityRow | undefined;
  let bestScore = 0;
  for (const row of existingRows) {
    if (!row.code) continue;
    if (row.entityType !== entityType) continue;
    if (row.workshopId === null || row.workshopId !== workshopId) continue;
    const score = similarity(row.code, code);
    if (score > bestScore) {
      best = row;
      bestScore = score;
    }
  }
  return bestScore > CODE_SIMILARITY_THRESHOLD ? best : undefined;
}

/** 名称+型号+车间综合相似分（> 0.8 需人工确认）最优候选 */
export function findComposite(
  existingRows: ExistingEntityRow[],
  item: { name?: string; model?: string },
  workshopId: string | null,
): CompositeMatch | undefined {
  const name: string = (item.name ?? '').trim();
  if (!name) return undefined;
  let best: CompositeMatch | undefined;
  for (const row of existingRows) {
    const nameSim = similarity(row.name, name);
    const modelSim = modelSimilarity(readEntityProperties(row.properties).model, item.model);
    const workshopSame = workshopId !== null && row.workshopId === workshopId ? 1 : 0;
    const score = nameSim * 0.6 + modelSim * 0.2 + workshopSame * 0.2;
    if (!best || score > best.score) {
      best = {
        candidate: row,
        score,
        reason: `名称相似度 ${nameSim.toFixed(2)}、型号相似度 ${modelSim.toFixed(2)}、车间一致 ${workshopSame}`,
      };
    }
  }
  return best;
}

export const COMPOSITE_MATCH_THRESHOLD = COMPOSITE_SCORE_THRESHOLD;
