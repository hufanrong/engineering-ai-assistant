import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, Merge } from 'lucide-react';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import { Checkbox } from '@client/src/components/ui/checkbox';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { batchDecideMerge, decideMerge, listMergeQueue } from '@client/src/api/entity';
import type {
  MergeDecision,
  MergeQueueCandidate,
  MergeQueueItem,
} from '@shared/api.interface';
import { ALIAS_SOURCE_LABELS } from '@shared/api.interface';

const PAGE_SIZE = 20;

interface MergeQueueTabProps {
  projectId: string;
  onOperated: () => void;
}

function formatScore(score: number): string {
  if (score > 0 && score <= 1) return `${Math.round(score * 100)}%`;
  return String(score);
}

interface CandidateColumnProps {
  candidate: MergeQueueCandidate;
}

const CandidateColumn = ({ candidate }: CandidateColumnProps) => (
  <div className="min-w-0 flex-1 space-y-1.5 rounded-md border border-border p-3">
    <div className="truncate text-sm font-medium">{candidate.name}</div>
    {candidate.code && (
      <div className="font-mono text-xs tabular-nums text-muted-foreground">
        {candidate.code}
      </div>
    )}
    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <span>{candidate.model ?? '型号未知'}</span>
      <span>·</span>
      <span>{candidate.workshopName ?? '车间未知'}</span>
    </div>
    <Badge variant="outline" className="text-xs">
      {ALIAS_SOURCE_LABELS[candidate.sourceType] ?? candidate.sourceType}
    </Badge>
  </div>
);

const MergeQueueTab = ({ projectId, onOperated }: MergeQueueTabProps) => {
  const [items, setItems] = useState<MergeQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [batching, setBatching] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listMergeQueue(projectId, {
        status: 'pending',
        offset: 0,
        limit: PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
      setSelectedIds([]);
    } catch {
      toast.error('加载归并待确认列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const handleDecision = async (id: string, decision: MergeDecision) => {
    setOperatingId(id);
    try {
      const result = await decideMerge(id, { decision });
      if (result.approvalRequestId) {
        toast.info('已提交审批，等待超级管理员审批');
      } else {
        toast.success('处理成功');
      }
      await loadItems();
      onOperated();
    } catch {
      toast.error('处理失败');
    } finally {
      setOperatingId(null);
    }
  };

  const handleBatch = async (decision: MergeDecision) => {
    if (selectedIds.length === 0) {
      toast.error('请先勾选待处理项');
      return;
    }
    setBatching(true);
    try {
      const result = await batchDecideMerge({ ids: selectedIds, decision });
      if (result.approvalRequestIds.length > 0) {
        toast.info(
          `已提交 ${result.approvalRequestIds.length} 项审批，等待超级管理员审批`,
        );
      } else {
        toast.success(`已批量处理 ${result.processed} 项`);
      }
      await loadItems();
      onOperated();
    } catch {
      toast.error('批量处理失败');
    } finally {
      setBatching(false);
    }
  };

  const toggleSelected = (id: string, checked: boolean | 'indeterminate') => {
    if (checked) {
      setSelectedIds((prev) => [...prev, id]);
    } else {
      setSelectedIds((prev) => prev.filter((v) => v !== id));
    }
  };

  if (loading && items.length === 0) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
        <div className="text-sm text-muted-foreground">暂无待确认归并项</div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">
          共 <span className="font-mono tabular-nums">{total}</span> 项待确认，已选
          <span className="mx-1 font-mono tabular-nums text-warning">
            {selectedIds.length}
          </span>
          项
        </span>
        <Button
          size="sm"
          data-ai-section-type="button"
          disabled={batching || selectedIds.length === 0}
          onClick={() => void handleBatch('confirmed_merge')}
        >
          {batching ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Merge className="mr-1 h-3.5 w-3.5" />}
          批量确认合并
        </Button>
        <Button
          size="sm"
          variant="outline"
          data-ai-section-type="button"
          disabled={batching || selectedIds.length === 0}
          onClick={() => void handleBatch('ignored')}
        >
          批量忽略
        </Button>
      </div>

      {items.map((item) => {
        const operating = operatingId === item.id;
        return (
          <div
            key={item.id}
            className={`space-y-3 rounded-md border border-border bg-card p-4 shadow-xs transition-opacity ${
              operating ? 'opacity-50' : ''
            }`}
          >
            <div className="flex items-start gap-3">
              <Checkbox
                checked={selectedIds.includes(item.id)}
                onCheckedChange={(checked: boolean | 'indeterminate') =>
                  toggleSelected(item.id, checked)
                }
                aria-label={`选择归并项 ${item.entityA.name}`}
                className="mt-1"
              />
              <div className="flex min-w-0 flex-1 items-stretch gap-3">
                <CandidateColumn candidate={item.entityA} />
                <div className="flex items-center">
                  <span className="rounded-full bg-muted px-2 py-1 text-xs font-semibold text-muted-foreground">
                    VS
                  </span>
                </div>
                <CandidateColumn candidate={item.entityB} />
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
              <div className="min-w-0 flex-1 text-xs text-muted-foreground">
                <span className="break-words">{item.matchReason}</span>
                <span className="ml-2 font-mono tabular-nums text-warning">
                  {formatScore(item.matchScore)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  data-ai-section-type="button"
                  disabled={operating}
                  onClick={() => void handleDecision(item.id, 'confirmed_merge')}
                >
                  确认合并
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  data-ai-section-type="button"
                  disabled={operating}
                  onClick={() => void handleDecision(item.id, 'confirmed_separate')}
                >
                  确认不同
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  data-ai-section-type="button"
                  disabled={operating}
                  onClick={() => void handleDecision(item.id, 'ignored')}
                >
                  忽略
                </Button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default MergeQueueTab;
