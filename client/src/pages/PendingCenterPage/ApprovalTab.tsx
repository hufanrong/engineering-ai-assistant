import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { Label } from '@client/src/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@client/src/components/ui/select';
import { Skeleton } from '@client/src/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@client/src/components/ui/table';
import { Textarea } from '@client/src/components/ui/textarea';
import { approveApproval, listApprovals, rejectApproval } from '@client/src/api/approval';
import { useIsSuperAdmin } from '@client/src/hooks/use-permission';
import type { ApprovalListItem } from '@shared/api.interface';
import {
  APPROVAL_REQUEST_TYPE_LABELS,
  APPROVAL_STATUS_LABELS,
} from '@shared/api.interface';
import { formatDateTime } from '@client/src/utils/time';

const PAGE_SIZE = 20;

const STATUS_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已批准' },
  { value: 'rejected', label: '已驳回' },
  { value: 'executed', label: '已执行' },
];

interface ApprovalTabProps {
  projectId: string;
  onOperated: () => void;
}

function showApiError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('无操作权限')) return;
  toast.error(message || '操作失败');
}

function statusBadgeClass(status: string): string {
  if (status === 'pending') return 'badge-warning';
  if (status === 'approved' || status === 'executed') return 'badge-success';
  return '';
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  if (status === 'rejected') {
    return <Badge variant="destructive">{label}</Badge>;
  }
  const cls = statusBadgeClass(status);
  if (cls) {
    return (
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
      >
        {label}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
      {label}
    </span>
  );
}

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function payloadEntries(payload: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(payload).map(
    ([key, value]): [string, string] => [key, formatPayloadValue(value)],
  );
}

const ApprovalTab = ({ projectId, onOperated }: ApprovalTabProps) => {
  const isSuperAdmin = useIsSuperAdmin();
  const [status, setStatus] = useState('all');
  const [requestType, setRequestType] = useState('all');
  const [items, setItems] = useState<ApprovalListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [detailItem, setDetailItem] = useState<ApprovalListItem | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ApprovalListItem | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [operatingId, setOperatingId] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);

  const loadItems = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      try {
        const data = await listApprovals(projectId, {
          status: status === 'all' ? undefined : status,
          requestType: requestType === 'all' ? undefined : requestType,
          offset: (targetPage - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
        });
        setItems(data.items);
        setTotal(data.total);
      } catch {
        toast.error('加载审批列表失败');
      } finally {
        setLoading(false);
      }
    },
    [projectId, status, requestType],
  );

  useEffect(() => {
    setPage(1);
    void loadItems(1);
  }, [loadItems]);

  const refresh = async () => {
    await loadItems(page);
    onOperated();
  };

  const handleApprove = async (item: ApprovalListItem) => {
    setOperatingId(item.id);
    try {
      await approveApproval(item.id);
      toast.success('已批准，已执行删除/归并操作');
      await refresh();
    } catch (err) {
      showApiError(err);
    } finally {
      setOperatingId(null);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setRejecting(true);
    try {
      await rejectApproval(rejectTarget.id, rejectReason.trim() || undefined);
      toast.success('已驳回');
      setRejectTarget(null);
      setRejectReason('');
      await refresh();
    } catch (err) {
      showApiError(err);
    } finally {
      setRejecting(false);
    }
  };

  const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const renderPayload = (item: ApprovalListItem) => {
    const entries = payloadEntries(item.payload);
    if (entries.length === 0) {
      return (
        <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          暂无详情数据
        </div>
      );
    }
    return (
      <div className="grid grid-cols-1 gap-2">
        {entries.map(([key, value]) => (
          <div
            key={key}
            className="flex items-baseline justify-between gap-3 rounded-md border border-border p-2 text-sm"
          >
            <span className="shrink-0 text-xs text-muted-foreground">{key}</span>
            <span className="min-w-0 break-words text-right">{value}</span>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {STATUS_FILTER_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={requestType} onValueChange={setRequestType}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {Object.entries(APPROVAL_REQUEST_TYPE_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
          共 {total} 条审批
        </span>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <div className="text-sm text-muted-foreground">暂无审批记录</div>
        </div>
      ) : (
        <div className="rounded-md border border-border bg-card shadow-xs">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-28">审批类型</TableHead>
                <TableHead>摘要</TableHead>
                <TableHead className="w-28">发起人</TableHead>
                <TableHead className="w-24">状态</TableHead>
                <TableHead className="w-36">发起时间</TableHead>
                <TableHead className="w-40 text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => {
                const operating = operatingId === item.id;
                return (
                  <TableRow key={item.id} className={operating ? 'opacity-50' : ''}>
                    <TableCell>
                      <Badge variant="outline">
                        {APPROVAL_REQUEST_TYPE_LABELS[item.requestType] ?? item.requestType}
                      </Badge>
                    </TableCell>
                    <TableCell className="min-w-0">
                      <button
                        type="button"
                        className="max-w-md truncate text-left text-sm hover:text-primary hover:underline"
                        onClick={() => setDetailItem(item)}
                      >
                        {item.summary || '-'}
                      </button>
                    </TableCell>
                    <TableCell className="text-sm">{item.requesterName}</TableCell>
                    <TableCell>
                      <StatusBadge
                        status={item.status}
                        label={APPROVAL_STATUS_LABELS[item.status] ?? item.status}
                      />
                    </TableCell>
                    <TableCell>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">
                        {formatDateTime(item.createdAt)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          data-ai-section-type="button"
                          onClick={() => setDetailItem(item)}
                        >
                          详情
                        </Button>
                        {isSuperAdmin && item.status === 'pending' && (
                          <>
                            <Button
                              size="sm"
                              data-ai-section-type="button"
                              disabled={operating}
                              onClick={() => void handleApprove(item)}
                            >
                              批准
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              data-ai-section-type="button"
                              disabled={operating}
                              onClick={() => {
                                setRejectTarget(item);
                                setRejectReason('');
                              }}
                            >
                              驳回
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2">
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {page} / {maxPage}
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page <= 1 || loading}
            onClick={() => {
              const next = page - 1;
              setPage(next);
              void loadItems(next);
            }}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={page >= maxPage || loading}
            onClick={() => {
              const next = page + 1;
              setPage(next);
              void loadItems(next);
            }}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      <Dialog
        open={detailItem !== null}
        onOpenChange={(next) => {
          if (!next) setDetailItem(null);
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>审批详情</DialogTitle>
            <DialogDescription>
              {detailItem
                ? `${APPROVAL_REQUEST_TYPE_LABELS[detailItem.requestType] ?? detailItem.requestType} · ${detailItem.summary}`
                : ''}
            </DialogDescription>
          </DialogHeader>
          {detailItem && (
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 text-sm font-medium">详情数据</div>
                {renderPayload(detailItem)}
              </div>
              <div className="space-y-1.5 text-sm">
                <div>
                  <span className="text-muted-foreground">发起人：</span>
                  {detailItem.requesterName}
                </div>
                <div>
                  <span className="text-muted-foreground">发起时间：</span>
                  <span className="font-mono text-xs tabular-nums">
                    {formatDateTime(detailItem.createdAt)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">审批人：</span>
                  {detailItem.approverName ?? '-'}
                </div>
                {detailItem.rejectReason && (
                  <div>
                    <span className="text-muted-foreground">驳回原因：</span>
                    {detailItem.rejectReason}
                  </div>
                )}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetailItem(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(next) => {
          if (!next) {
            setRejectTarget(null);
            setRejectReason('');
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>驳回审批</DialogTitle>
            <DialogDescription>
              {rejectTarget
                ? `驳回「${APPROVAL_REQUEST_TYPE_LABELS[rejectTarget.requestType] ?? rejectTarget.requestType}」审批，驳回后原操作不会执行`
                : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="reject-reason">驳回原因（可选）</Label>
            <Textarea
              id="reject-reason"
              placeholder="请输入驳回原因"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRejectTarget(null);
                setRejectReason('');
              }}
              disabled={rejecting}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              data-ai-section-type="button"
              disabled={rejecting}
              onClick={() => void handleReject()}
            >
              {rejecting && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              确认驳回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ApprovalTab;
