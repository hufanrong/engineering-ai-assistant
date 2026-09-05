import { useCallback, useEffect, useState } from 'react';
import { Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import { Input } from '@client/src/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@client/src/components/ui/select';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { Table, type TableColumnsType } from '@lark-apaas/client-toolkit/antd-table';
import { useParams } from 'react-router-dom';
import DeleteConfirmDialog from '@client/src/components/DeleteConfirmDialog';
import { useIsSuperAdmin } from '@client/src/hooks/use-permission';
import { deleteEntity, listEntities } from '@client/src/api/entity';
import type { EntityListItem } from '@shared/api.interface';
import { ENTITY_TYPE_LABELS } from '@shared/api.interface';
import EntityDetailDrawer from './EntityDetailDrawer';

const PAGE_SIZE = 20;

const ENTITY_TYPE_KEYS = Object.keys(ENTITY_TYPE_LABELS);
const MERGE_STATUS_KEYS = ['merged', 'pending', 'standalone'];
const MERGE_STATUS_LABEL_MAP: Record<string, string> = {
  merged: '已归并',
  pending: '待确认',
  standalone: '独立',
};

function mergeStatusBadgeClass(status: string): string {
  if (status === 'merged') return 'badge-success';
  if (status === 'pending') return 'badge-warning';
  return 'bg-muted text-muted-foreground';
}

function showApiError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('无操作权限')) return;
  toast.error(message || '操作失败');
}

const EntityManagementPage = () => {
  const { id: projectId } = useParams<{ id: string }>();
  const isSuperAdmin = useIsSuperAdmin();

  const [entityType, setEntityType] = useState('all');
  const [mergeStatus, setMergeStatus] = useState('all');
  const [keywordInput, setKeywordInput] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');

  const [entities, setEntities] = useState<EntityListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [drawerEntityId, setDrawerEntityId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EntityListItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadEntities = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await listEntities(projectId, {
        entityType: entityType === 'all' ? undefined : entityType,
        mergeStatus: mergeStatus === 'all' ? undefined : mergeStatus,
        keyword: appliedKeyword || undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setEntities(data.items);
      setTotal(data.total);
    } catch {
      toast.error('加载实体列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, entityType, mergeStatus, appliedKeyword, page]);

  useEffect(() => {
    void loadEntities();
  }, [loadEntities]);

  const handleSearch = () => {
    setAppliedKeyword(keywordInput.trim());
    setPage(1);
  };

  const columns: TableColumnsType<EntityListItem> = [
    {
      title: '标准编号',
      dataIndex: 'code',
      width: 180,
      ellipsis: true,
      render: (value: string | null) =>
        value ? (
          <span className="font-mono font-bold tabular-nums">{value}</span>
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 220,
      ellipsis: true,
      render: (value: string) => <span className="font-medium">{value}</span>,
    },
    {
      title: '类型',
      dataIndex: 'entityType',
      width: 100,
      render: (value: string) => (
        <Badge variant="outline">{ENTITY_TYPE_LABELS[value] ?? value}</Badge>
      ),
    },
    {
      title: '型号',
      dataIndex: 'model',
      width: 140,
      ellipsis: true,
      render: (value: string | undefined) => value ?? '-',
    },
    {
      title: '车间',
      dataIndex: 'workshopName',
      width: 120,
      ellipsis: true,
      render: (value: string | undefined) => value ?? '-',
    },
    {
      title: '别名数',
      dataIndex: 'aliasCount',
      width: 90,
      render: (value: number) => (
        <span className="font-mono tabular-nums">{value}</span>
      ),
    },
    {
      title: '归并状态',
      dataIndex: 'mergeStatus',
      width: 100,
      render: (value: string) => (
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${mergeStatusBadgeClass(value)}`}
        >
          {MERGE_STATUS_LABEL_MAP[value] ?? value}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 70,
      fixed: 'right',
      render: (_: unknown, record: EntityListItem) => (
        <Button
          variant="ghost"
          size="sm"
          data-ai-section-type="button"
          aria-label={`删除实体 ${record.name}`}
          onClick={(e) => {
            e.stopPropagation();
            setDeleteTarget(record);
          }}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      ),
    },
  ];

  const handleRowClick = (record: EntityListItem) => {
    setDrawerEntityId(record.id);
    setDrawerOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const result = await deleteEntity(deleteTarget.id);
      if (result.status === 'executed') {
        toast.success('已删除');
      } else {
        toast.success('已提交审批，等待超级管理员审批');
      }
      setDeleteTarget(null);
      await loadEntities();
    } catch (err) {
      showApiError(err);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4 p-4" data-ai-section-type="card-list">
      <div>
        <h1 className="text-xl font-semibold">实体管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          设备与材料实体的别名、属性与归并状态管理
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索名称、编号或别名"
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSearch();
            }}
            className="pl-8"
          />
        </div>
        <Select
          value={entityType}
          onValueChange={(value) => {
            setEntityType(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-32">
            <SelectValue placeholder="全部类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {ENTITY_TYPE_KEYS.map((key) => (
              <SelectItem key={key} value={key}>
                {ENTITY_TYPE_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={mergeStatus}
          onValueChange={(value) => {
            setMergeStatus(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-32">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {MERGE_STATUS_KEYS.map((key) => (
              <SelectItem key={key} value={key}>
                {MERGE_STATUS_LABEL_MAP[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button data-ai-section-type="button" onClick={handleSearch}>
          查询
        </Button>
      </div>

      {loading && entities.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : entities.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <div className="text-sm text-muted-foreground">
            {appliedKeyword ? '未找到匹配的实体' : '暂无实体，解析资料后将自动提取'}
          </div>
        </div>
      ) : (
        <div className="rounded-md border border-border bg-card shadow-xs">
          <Table
            columns={columns}
            dataSource={entities}
            loading={loading}
            rowKey="id"
            scroll={{ x: 950, y: 500 }}
            onRow={(record: EntityListItem) => ({
              onClick: () => handleRowClick(record),
              style: { cursor: 'pointer' },
            })}
            pagination={{
              current: page,
              pageSize: PAGE_SIZE,
              total,
              onChange: (nextPage: number) => setPage(nextPage),
            }}
          />
        </div>
      )}

      <EntityDetailDrawer
        entityId={drawerEntityId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onChanged={() => void loadEntities()}
      />

      <DeleteConfirmDialog
        open={deleteTarget !== null}
        itemLabel="实体"
        itemName={deleteTarget?.name}
        isSuperAdmin={isSuperAdmin}
        submitting={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
};

export default EntityManagementPage;
