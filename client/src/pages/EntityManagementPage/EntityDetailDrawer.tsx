import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ArrowLeftRight, Loader2, Plus } from 'lucide-react';

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
import { addEntityAlias, getEntityDetail } from '@client/src/api/entity';
import type { EntityDetail } from '@shared/api.interface';
import {
  ALIAS_SOURCE_LABELS,
  ENTITY_TYPE_LABELS,
  RELATIONSHIP_TYPE_LABELS,
} from '@shared/api.interface';

interface EntityDetailDrawerProps {
  entityId: string | null;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}

function mergeStatusBadgeClass(status: string): string {
  if (status === 'merged') return 'badge-success';
  if (status === 'pending') return 'badge-warning';
  return 'bg-muted text-muted-foreground';
}

const MERGE_STATUS_LABEL_MAP: Record<string, string> = {
  merged: '已归并',
  pending: '待确认',
  standalone: '独立',
};

const PROPERTY_ROWS: Array<{ key: string; label: string }> = [
  { key: 'model', label: '型号' },
  { key: 'spec', label: '规格' },
  { key: 'material', label: '材质' },
  { key: 'quantity', label: '数量' },
];

function propertyValue(detail: EntityDetail, key: string): string {
  const properties: Record<string, string | undefined> = {
    model: detail.properties.model,
    spec: detail.properties.spec,
    material: detail.properties.material,
    quantity: detail.properties.quantity,
  };
  return properties[key] ?? '-';
}

const EntityDetailDrawer = ({
  entityId,
  open,
  onClose,
  onChanged,
}: EntityDetailDrawerProps) => {
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [aliasDialogOpen, setAliasDialogOpen] = useState(false);
  const [aliasName, setAliasName] = useState('');
  const [aliasCode, setAliasCode] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadDetail = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const data = await getEntityDetail(id);
      setDetail(data);
    } catch {
      toast.error('加载实体详情失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && entityId) {
      setAliasName('');
      setAliasCode('');
      void loadDetail(entityId);
    }
    if (!open) {
      setDetail(null);
    }
  }, [open, entityId, loadDetail]);

  const handleAddAlias = async () => {
    if (!detail || (!aliasName.trim() && !aliasCode.trim())) {
      toast.error('请填写别名名称或别名编号');
      return;
    }
    setSubmitting(true);
    try {
      await addEntityAlias(detail.id, {
        aliasName: aliasName.trim() || undefined,
        aliasCode: aliasCode.trim() || undefined,
        sourceType: 'manual',
      });
      toast.success('别名已添加');
      setAliasDialogOpen(false);
      setAliasName('');
      setAliasCode('');
      await loadDetail(detail.id);
      onChanged();
    } catch {
      toast.error('添加别名失败');
    } finally {
      setSubmitting(false);
    }
  };

  const renderRelationships = (entity: EntityDetail) => {
    if (entity.relationships.length === 0) {
      return (
        <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          暂无关联关系
        </div>
      );
    }
    return (
      <div className="space-y-2">
        {entity.relationships.map((rel) => (
          <div
            key={rel.id}
            className="flex items-center justify-between rounded-md border border-border p-2 text-sm"
          >
            <span className="flex items-center gap-2">
              <ArrowLeftRight className="h-3.5 w-3.5 text-muted-foreground" />
              <Badge variant="outline">
                {RELATIONSHIP_TYPE_LABELS[rel.relationshipType] ?? rel.relationshipType}
              </Badge>
              <span className="text-muted-foreground">
                {rel.direction === 'out' ? '指向' : '来自'}
              </span>
              <span className="font-medium">{rel.targetEntity.name}</span>
            </span>
            {rel.targetEntity.code && (
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {rel.targetEntity.code}
              </span>
            )}
          </div>
        ))}
      </div>
    );
  };

  const renderConflicts = (entity: EntityDetail) => {
    if (entity.conflicts.length === 0) return null;
    return (
      <div>
        <div className="mb-1 text-sm font-medium">
          版本冲突（{entity.conflicts.length}）
        </div>
        <div className="space-y-2">
          {entity.conflicts.map((conflict) => (
            <div
              key={conflict.id}
              className="flex items-center justify-between rounded-md border border-destructive/30 bg-destructive/5 p-2 text-sm"
            >
              <span>{conflict.fieldName}</span>
              <span className="inline-flex items-center rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                待处理
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <Sheet open={open} onOpenChange={(next) => (next ? undefined : onClose())}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{detail?.name ?? '实体详情'}</SheetTitle>
          <SheetDescription>别名、属性、关联关系与冲突信息</SheetDescription>
        </SheetHeader>

        {loading || !detail ? (
          <div className="space-y-3 p-4">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <div className="space-y-5 px-4 pb-8">
            <div className="flex flex-wrap items-center gap-2">
              {detail.code && (
                <span className="font-mono text-sm font-bold tabular-nums">
                  {detail.code}
                </span>
              )}
              <Badge variant="outline">
                {ENTITY_TYPE_LABELS[detail.entityType] ?? detail.entityType}
              </Badge>
              <Badge className={`${mergeStatusBadgeClass(detail.mergeStatus)} rounded-full`}>
                {MERGE_STATUS_LABEL_MAP[detail.mergeStatus] ?? detail.mergeStatus}
              </Badge>
            </div>

            {detail.workshop && (
              <div className="text-sm">
                <span className="text-muted-foreground">所属车间：</span>
                {detail.workshop.name}
              </div>
            )}

            <div>
              <div className="mb-1 flex items-center justify-between">
                <div className="text-sm font-medium">别名（{detail.aliases.length}）</div>
                <Button
                  variant="outline"
                  size="sm"
                  data-ai-section-type="button"
                  onClick={() => setAliasDialogOpen(true)}
                >
                  <Plus className="mr-1 h-3.5 w-3.5" />
                  添加别名
                </Button>
              </div>
              {detail.aliases.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
                  暂无别名
                </div>
              ) : (
                <div className="space-y-2">
                  {detail.aliases.map((alias) => (
                    <div
                      key={alias.id}
                      className={`flex items-center justify-between rounded-md border p-2 text-sm ${
                        alias.isPrimary
                          ? 'border-primary/60 bg-primary/5'
                          : 'border-border'
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">
                            {alias.aliasName ?? '-'}
                          </span>
                          {alias.isPrimary && (
                            <Badge className="rounded-full bg-primary/10 text-primary">
                              主别名
                            </Badge>
                          )}
                        </div>
                        {alias.aliasCode && (
                          <div className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
                            {alias.aliasCode}
                          </div>
                        )}
                      </div>
                      <Badge variant="outline">
                        {ALIAS_SOURCE_LABELS[alias.sourceType] ?? alias.sourceType}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="mb-1 text-sm font-medium">属性</div>
              <div className="grid grid-cols-2 gap-2">
                {PROPERTY_ROWS.map((row) => (
                  <div key={row.key} className="rounded-md border border-border p-2">
                    <div className="text-xs text-muted-foreground">{row.label}</div>
                    <div className="mt-0.5 truncate text-sm">{propertyValue(detail, row.key)}</div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-1 text-sm font-medium">关联关系</div>
              {renderRelationships(detail)}
            </div>

            {renderConflicts(detail)}
          </div>
        )}
      </SheetContent>

      <Dialog open={aliasDialogOpen} onOpenChange={setAliasDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>添加别名</DialogTitle>
            <DialogDescription>人工补充的别名将用于后续实体归并</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="alias-name">别名名称</Label>
              <Input
                id="alias-name"
                value={aliasName}
                placeholder="请输入别名名称"
                onChange={(e) => setAliasName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alias-code">别名编号</Label>
              <Input
                id="alias-code"
                value={aliasCode}
                placeholder="请输入别名编号"
                onChange={(e) => setAliasCode(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAliasDialogOpen(false)}>
              取消
            </Button>
            <Button disabled={submitting} onClick={() => void handleAddAlias()}>
              {submitting && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              确认添加
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  );
};

export default EntityDetailDrawer;
