import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { FileText, Loader2, Tag } from 'lucide-react';

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
import { Input } from '@client/src/components/ui/input';
import { Label } from '@client/src/components/ui/label';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@client/src/components/ui/sheet';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { getRecordDetail, supplementRecord, updateRecord } from '@client/src/api/record';
import type {
  RecordDetail,
  RecordTypeConfigItem,
} from '@shared/api.interface';
import { RECORD_STATUS_LABELS } from '@shared/api.interface';
import { UniversalLink } from '@lark-apaas/client-toolkit/components/UniversalLink';

interface RecordDetailDrawerProps {
  recordId: string | null;
  open: boolean;
  onClose: () => void;
  typeConfigs: RecordTypeConfigItem[];
  onChanged: () => void;
}

function completenessColor(value: number): string {
  if (value >= 100) return 'bg-success';
  if (value >= 60) return 'bg-warning';
  return 'bg-destructive';
}

function statusBadgeClass(status: string): string {
  if (status === 'complete') return 'badge-success';
  if (status === 'pending_supplement') return 'badge-warning';
  return 'bg-muted text-muted-foreground';
}

const RecordDetailDrawer = ({
  recordId,
  open,
  onClose,
  typeConfigs,
  onChanged,
}: RecordDetailDrawerProps) => {
  const [detail, setDetail] = useState<RecordDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [typeDialogOpen, setTypeDialogOpen] = useState(false);
  const [selectedType, setSelectedType] = useState('');
  const [changingType, setChangingType] = useState(false);
  const [supplementValues, setSupplementValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const data = await getRecordDetail(id);
      setDetail(data);
    } catch {
      toast.error('加载记录详情失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && recordId) {
      setSupplementValues({});
      void loadDetail(recordId);
    }
    if (!open) {
      setDetail(null);
    }
  }, [open, recordId, loadDetail]);

  const handleChangeType = async () => {
    if (!detail || !selectedType || selectedType === detail.recordType) {
      setTypeDialogOpen(false);
      return;
    }
    setChangingType(true);
    try {
      await updateRecord(detail.id, { recordType: selectedType });
      toast.success('记录类型已更新');
      setTypeDialogOpen(false);
      await loadDetail(detail.id);
      onChanged();
    } catch {
      toast.error('更新类型失败');
    } finally {
      setChangingType(false);
    }
  };

  const handleSupplement = async () => {
    if (!detail) return;
    const supplements = Object.entries(supplementValues)
      .filter(([, value]) => value.trim().length > 0)
      .map(([key, value]) => ({ key, value: value.trim() }));
    if (supplements.length === 0) {
      toast.error('请填写至少一项补充内容');
      return;
    }
    setSubmitting(true);
    try {
      const result = await supplementRecord(detail.id, { supplements });
      setDetail({
        ...detail,
        status: result.status,
        completeness: result.completeness,
        missingFields: result.missingFields,
      });
      setSupplementValues({});
      onChanged();
      if (result.completeness >= 100) {
        toast.success('已补充完整');
      } else {
        toast.success('补充内容已提交');
      }
    } catch {
      toast.error('提交补充内容失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{detail?.title ?? '记录详情'}</SheetTitle>
          <SheetDescription>现场记录内容、完整度与关联信息</SheetDescription>
        </SheetHeader>

        {loading || !detail ? (
          <div className="space-y-3 p-4">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <div className="space-y-5 px-4 pb-8">            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                data-ai-section-type="button"
                onClick={() => {
                  setSelectedType(detail.recordType);
                  setTypeDialogOpen(true);
                }}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium transition-colors hover:border-primary/50 hover:text-primary"
              >
                <Tag className="h-3 w-3" />
                {detail.recordTypeName}
                <span className="text-muted-foreground">点击修改</span>
              </button>
              <Badge className={`${statusBadgeClass(detail.status)} rounded-full`}>
                {RECORD_STATUS_LABELS[detail.status] ?? detail.status}
              </Badge>
              {detail.typeModified && <Badge variant="outline" className="text-xs">已人工调整</Badge>}
            </div>

            <div className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">完整度</span>
                <span className="font-mono tabular-nums font-semibold">
                  {detail.completeness}%
                </span>
              </div>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-all ${completenessColor(detail.completeness)}`}
                  style={{ width: `${detail.completeness}%` }}
                />
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                类型置信度
                <span className="ml-1 font-mono tabular-nums">
                  {Math.round(detail.typeConfidence * 100)}%
                </span>
              </div>
            </div>

            <div>
              <div className="mb-1 text-sm font-medium">记录内容</div>
              <div className="whitespace-pre-wrap break-words rounded-md border border-border p-3 text-sm">
                {detail.content || '暂无内容'}
              </div>
              {detail.location && (
                <div className="mt-2 text-xs text-muted-foreground">位置：{detail.location}</div>
              )}
            </div>

            {detail.missingFields.length > 0 && (
              <div>
                <div className="mb-1 text-sm font-medium">缺失项（{detail.missingFields.length}）</div>
                <div className="space-y-3 rounded-md border border-border p-3">
                  {detail.missingFields.map((field) => (
                    <div key={field.key} className="space-y-1.5">
                      <Label htmlFor={`sup-${field.key}`}>{field.label}</Label>
                      <Input id={`sup-${field.key}`} value={supplementValues[field.key] ?? ''}
                        placeholder={`请输入${field.label}`}
                        onChange={(e) => setSupplementValues((prev) => ({ ...prev, [field.key]: e.target.value }))} />
                    </div>
                  ))}
                  <Button className="w-full" disabled={submitting} onClick={() => void handleSupplement()}>
                    {submitting ? '提交中...' : '提交补充'}
                  </Button>
                </div>
              </div>
            )}

            {detail.workshop && (
              <div className="text-sm"><span className="text-muted-foreground">所属车间：</span>{detail.workshop.name}</div>
            )}

            <div>
              <div className="mb-1 text-sm font-medium">关联实体</div>
              {detail.relatedEntities.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">暂未关联实体</div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {detail.relatedEntities.map((entity) => (
                    <Badge key={entity.id} variant="outline">{entity.name}</Badge>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="mb-1 text-sm font-medium">附件</div>
              {detail.attachments.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">暂无附件</div>
              ) : (
                <div className="space-y-2">
                  {detail.attachments.map((file) => (
                    <UniversalLink key={file.id} to={file.fileUrl} target="_blank" rel="noopener noreferrer"
                      className="flex items-center gap-2 rounded-md border border-border p-2 text-sm break-all transition-colors hover:border-primary/50 hover:text-primary">
                      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                      {file.filename}
                    </UniversalLink>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </SheetContent>

      <Dialog open={typeDialogOpen} onOpenChange={setTypeDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>选择记录类型</DialogTitle>
            <DialogDescription>确认后将按新类型重新计算完整性</DialogDescription>
          </DialogHeader>
          <div className="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto">
            {typeConfigs.map((config) => (
              <button
                key={config.recordType}
                type="button"
                onClick={() => setSelectedType(config.recordType)}
                className={`rounded-md border p-2 text-left text-sm transition-colors ${
                  selectedType === config.recordType
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:border-primary/40'
                }`}
              >
                {config.displayName}
              </button>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTypeDialogOpen(false)}>
              取消
            </Button>
            <Button disabled={changingType} onClick={() => void handleChangeType()}>
              {changingType && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  );
};

export default RecordDetailDrawer;
