import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';

import { Button } from '@client/src/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { Input } from '@client/src/components/ui/input';
import { Label } from '@client/src/components/ui/label';
import { Skeleton } from '@client/src/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@client/src/components/ui/table';
import { listConflicts, resolveConflict } from '@client/src/api/entity';
import type { ConflictListItem } from '@shared/api.interface';

const PAGE_SIZE = 20;

interface ConflictTabProps {
  projectId: string;
  onOperated: () => void;
}

function ValueCell({ value, source }: { value: string | null; source: string | null }) {
  return (
    <div className="min-w-0">
      <div className="break-words text-sm">{value ?? '-'}</div>
      {source && (
        <div className="mt-0.5 text-xs text-muted-foreground">来源：{source}</div>
      )}
    </div>
  );
}

const ConflictTab = ({ projectId, onOperated }: ConflictTabProps) => {
  const [items, setItems] = useState<ConflictListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [manualItem, setManualItem] = useState<ConflictListItem | null>(null);
  const [manualValue, setManualValue] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listConflicts(projectId, {
        status: 'pending',
        offset: 0,
        limit: PAGE_SIZE,
      });
      setItems(data.items);
    } catch {
      toast.error('加载冲突列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const handleResolve = async (
    id: string,
    resolution: 'resolved_a' | 'resolved_b' | 'resolved_manual',
    resolvedValue?: string,
  ) => {
    setOperatingId(id);
    try {
      const result = await resolveConflict(id, { resolution, resolvedValue });
      if (result.approvalRequestId) {
        toast.info('已提交审批，等待超级管理员审批');
      } else {
        toast.success('冲突已处理');
      }
      await loadItems();
      onOperated();
    } catch {
      toast.error('处理冲突失败');
    } finally {
      setOperatingId(null);
    }
  };

  const handleManualSubmit = async () => {
    if (!manualItem) return;
    if (!manualValue.trim()) {
      toast.error('请输入手动确认的值');
      return;
    }
    setSubmitting(true);
    try {
      await handleResolve(manualItem.id, 'resolved_manual', manualValue.trim());
      setManualItem(null);
      setManualValue('');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && items.length === 0) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
        <div className="text-sm text-muted-foreground">暂无待处理冲突</div>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-card shadow-xs">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-36">字段名</TableHead>
            <TableHead>实体</TableHead>
            <TableHead className="w-56">A 值</TableHead>
            <TableHead className="w-56">B 值</TableHead>
            <TableHead className="w-52 text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => {
            const operating = operatingId === item.id;
            return (
              <TableRow key={item.id} className={operating ? 'opacity-50' : ''}>
                <TableCell className="font-medium">{item.fieldName}</TableCell>
                <TableCell className="min-w-0">
                  <div className="truncate text-sm">{item.entityName}</div>
                  {item.entityCode && (
                    <div className="font-mono text-xs tabular-nums text-muted-foreground">
                      {item.entityCode}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <ValueCell value={item.valueA} source={item.sourceA} />
                </TableCell>
                <TableCell>
                  <ValueCell value={item.valueB} source={item.sourceB} />
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      data-ai-section-type="button"
                      disabled={operating}
                      onClick={() => void handleResolve(item.id, 'resolved_a')}
                    >
                      选 A
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      data-ai-section-type="button"
                      disabled={operating}
                      onClick={() => void handleResolve(item.id, 'resolved_b')}
                    >
                      选 B
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      data-ai-section-type="button"
                      disabled={operating}
                      onClick={() => {
                        setManualItem(item);
                        setManualValue('');
                      }}
                    >
                      手动输入
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <Dialog
        open={manualItem !== null}
        onOpenChange={(next) => {
          if (!next) {
            setManualItem(null);
            setManualValue('');
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>手动确认字段值</DialogTitle>
            <DialogDescription>
              {manualItem ? `${manualItem.entityName} · ${manualItem.fieldName}` : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="manual-value">确认后的值</Label>
            <Input
              id="manual-value"
              value={manualValue}
              placeholder="请输入字段值"
              onChange={(e) => setManualValue(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setManualItem(null);
                setManualValue('');
              }}
            >
              取消
            </Button>
            <Button disabled={submitting} onClick={() => void handleManualSubmit()}>
              {submitting && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ConflictTab;
