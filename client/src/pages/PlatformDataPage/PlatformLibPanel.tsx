import { useCallback, useEffect, useState } from 'react';
import { Pencil, Plus, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

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
import { Textarea } from '@client/src/components/ui/textarea';
import {
  Table,
  type TableColumnsType,
} from '@lark-apaas/client-toolkit/antd-table';
import type { PlatformListResponse } from '@shared/api.interface';
import type { PlatformListParams } from '@client/src/api/platform';

const PAGE_SIZE = 20;

export interface PlatformFieldConfig {
  key: string;
  label: string;
  required?: boolean;
  multiline?: boolean;
  placeholder?: string;
}

export interface PlatformLibPanelProps<T> {
  libLabel: string;
  fields: PlatformFieldConfig[];
  columns: TableColumnsType<T>;
  listApi: (params: PlatformListParams) => Promise<PlatformListResponse<T>>;
  createApi: (body: Record<string, string>) => Promise<void>;
  updateApi: (id: string, body: Record<string, string>) => Promise<void>;
  deleteApi: (id: string) => Promise<void>;
  toFormValues: (item: T) => Record<string, string>;
  onTotalChange: (total: number) => void;
}

const buildEmptyValues = (fields: PlatformFieldConfig[]): Record<string, string> => {
  const values: Record<string, string> = {};
  for (const field of fields) values[field.key] = '';
  return values;
};

function PlatformLibPanel<T extends { id: string }>({
  libLabel,
  fields,
  columns,
  listApi,
  createApi,
  updateApi,
  deleteApi,
  toFormValues,
  onTotalChange,
}: PlatformLibPanelProps<T>) {
  const [keywordInput, setKeywordInput] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<T | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>(() =>
    buildEmptyValues(fields),
  );
  const [submitting, setSubmitting] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<T | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listApi({
        keyword: appliedKeyword || undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
      onTotalChange(data.total);
    } catch {
      toast.error(`加载${libLabel}列表失败`);
    } finally {
      setLoading(false);
    }
    // onTotalChange 需由父组件传入稳定引用（useCallback）
  }, [listApi, appliedKeyword, page, onTotalChange]);

  useEffect(() => {
    void loadItems();
  }, [loadItems]);

  const handleSearch = () => {
    setAppliedKeyword(keywordInput.trim());
    setPage(1);
  };

  const openCreate = () => {
    setEditing(null);
    setFormValues(buildEmptyValues(fields));
    setFormOpen(true);
  };

  const openEdit = (item: T) => {
    setEditing(item);
    setFormValues({ ...buildEmptyValues(fields), ...toFormValues(item) });
    setFormOpen(true);
  };

  const handleSubmit = async () => {
    const missing = fields.find(
      (field: PlatformFieldConfig) =>
        field.required && !formValues[field.key]?.trim(),
    );
    if (missing) {
      toast.error(`请填写「${missing.label}」`);
      return;
    }
    setSubmitting(true);
    try {
      if (editing) {
        await updateApi(editing.id, formValues);
        toast.success(`${libLabel}条目已更新`);
      } else {
        await createApi(formValues);
        toast.success(`${libLabel}条目已新增`);
      }
      setFormOpen(false);
      setPage(1);
      await loadItems();
    } catch {
      toast.error(editing ? `更新${libLabel}条目失败` : `新增${libLabel}条目失败`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteApi(deleteTarget.id);
      toast.success(`${libLabel}条目已删除`);
      setDeleteTarget(null);
      await loadItems();
    } catch {
      toast.error(`删除${libLabel}条目失败`);
    } finally {
      setDeleting(false);
    }
  };

  const actionColumn: TableColumnsType<T>[number] = {
    title: '操作',
    key: 'platform-actions',
    width: 130,
    fixed: 'right',
    render: (_value: unknown, record: T) => (
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => openEdit(record)}
        >
          <Pencil className="mr-1 h-3 w-3" />
          编辑
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-destructive hover:text-destructive"
          onClick={() => setDeleteTarget(record)}
        >
          <Trash2 className="mr-1 h-3 w-3" />
          删除
        </Button>
      </div>
    ),
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索关键字"
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSearch();
            }}
            className="pl-8"
          />
        </div>
        <Button data-ai-section-type="button" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          新增
        </Button>
      </div>

      {loading && items.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i: number) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border">
          <p className="text-sm text-muted-foreground">
            {appliedKeyword ? '未找到匹配的条目' : `${libLabel}暂无数据`}
          </p>
          <Button variant="outline" size="sm" onClick={openCreate}>
            <Plus className="mr-1 h-4 w-4" />
            新增第一条
          </Button>
        </div>
      ) : (
        <div className="rounded-md border border-border bg-card shadow-xs">
          <Table
            columns={[...columns, actionColumn]}
            dataSource={items}
            loading={loading}
            rowKey="id"
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total,
              onChange: (nextPage: number) => setPage(nextPage),
            }}
          />
        </div>
      )}

      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editing ? `编辑${libLabel}条目` : `新增${libLabel}条目`}
            </DialogTitle>
            <DialogDescription>
              平台级数据全局共享，提交后立即对所有项目生效
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2 sm:grid-cols-2">
            {fields.map((field: PlatformFieldConfig) => (
              <div
                key={field.key}
                className={field.multiline ? 'sm:col-span-2' : undefined}
              >
                <Label htmlFor={`platform-field-${field.key}`}>
                  {field.label}
                  {field.required ? (
                    <span className="ml-0.5 text-destructive">*</span>
                  ) : null}
                </Label>
                {field.multiline ? (
                  <Textarea
                    id={`platform-field-${field.key}`}
                    placeholder={field.placeholder}
                    value={formValues[field.key] ?? ''}
                    onChange={(e) =>
                      setFormValues((prev: Record<string, string>) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    className="mt-1.5 min-h-20"
                  />
                ) : (
                  <Input
                    id={`platform-field-${field.key}`}
                    placeholder={field.placeholder}
                    value={formValues[field.key] ?? ''}
                    onChange={(e) =>
                      setFormValues((prev: Record<string, string>) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    className="mt-1.5"
                  />
                )}
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setFormOpen(false)}
              disabled={submitting}
            >
              取消
            </Button>
            <Button onClick={() => void handleSubmit()} disabled={submitting}>
              {submitting ? '提交中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open: boolean) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
            <DialogDescription>
              删除后不可恢复，所有项目的检索将不再融合该条数据，确定删除吗？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDelete()}
              disabled={deleting}
            >
              {deleting ? '删除中…' : '删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default PlatformLibPanel;
