import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import DeleteConfirmDialog from '@client/src/components/DeleteConfirmDialog';
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
import { listProjects } from '@client/src/api/project';
import {
  deleteSiteRecord,
  getRecordTypeConfigs,
  listSiteRecords,
} from '@client/src/api/record';
import { useIsSuperAdmin } from '@client/src/hooks/use-permission';
import type {
  RecordListItem,
  RecordTypeConfigItem,
} from '@shared/api.interface';
import { RECORD_STATUS, RECORD_STATUS_LABELS } from '@shared/api.interface';
import { formatDate, formatDateTime } from '@client/src/utils/time';
import RecordDetailDrawer from './RecordDetailDrawer';

const PAGE_SIZE = 20;

function completenessColor(value: number): string {
  if (value >= 100) return 'bg-success';
  if (value >= 60) return 'bg-warning';
  return 'bg-destructive';
}

function statusBadgeClass(status: string): string {
  if (status === RECORD_STATUS.COMPLETE) return 'badge-success';
  if (status === RECORD_STATUS.PENDING_SUPPLEMENT) return 'badge-warning';
  return 'bg-muted text-muted-foreground';
}

function showApiError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('无操作权限')) return;
  toast.error(message || '操作失败');
}

const RecordManagementPage = () => {
  const isSuperAdmin = useIsSuperAdmin();
  const [searchParams, setSearchParams] = useSearchParams();
  const [projectId, setProjectId] = useState(searchParams.get('projectId') ?? 'all');
  const [recordType, setRecordType] = useState('all');
  const [status, setStatus] = useState(searchParams.get('status') ?? 'all');
  const [keyword, setKeyword] = useState('');

  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [typeConfigs, setTypeConfigs] = useState<RecordTypeConfigItem[]>([]);
  const [records, setRecords] = useState<RecordListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [drawerRecordId, setDrawerRecordId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<RecordListItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [projectData, configData] = await Promise.all([
          listProjects(),
          getRecordTypeConfigs(),
        ]);
        setProjects(projectData.items.map((p) => ({ id: p.id, name: p.name })));
        setTypeConfigs(configData.items);
      } catch {
        toast.error('加载筛选数据失败');
      }
    })();
  }, []);

  const loadRecords = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSiteRecords({
        projectId: projectId === 'all' ? undefined : projectId,
        recordType: recordType === 'all' ? undefined : recordType,
        status: status === 'all' ? undefined : status,
        keyword: keyword.trim() || undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setRecords(data.items);
      setTotal(data.total);
    } catch {
      toast.error('加载记录列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, recordType, status, keyword, page]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadRecords();
    }, 300);
    return () => clearTimeout(timer);
  }, [loadRecords]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (projectId !== 'all') next.set('projectId', projectId);
    if (status !== 'all') next.set('status', status);
    setSearchParams(next, { replace: true });
  }, [projectId, status, setSearchParams]);

  const columns: TableColumnsType<RecordListItem> = [
    {
      title: '标题',
      dataIndex: 'title',
      width: 220,
      ellipsis: true,
      render: (value: string) => <span className="font-medium">{value}</span>,
    },
    {
      title: '类型',
      dataIndex: 'recordTypeName',
      width: 120,
      render: (value: string) => <Badge variant="outline">{value}</Badge>,
    },
    { title: '项目', dataIndex: 'projectName', width: 140, ellipsis: true },
    {
      title: '车间',
      dataIndex: 'workshopName',
      width: 110,
      ellipsis: true,
      render: (value: string | undefined) => value ?? '-',
    },
    {
      title: '日期',
      dataIndex: 'recordDate',
      width: 110,
      render: (value: string | undefined, _record: RecordListItem) =>
        value ? (
          <span className="font-mono tabular-nums">{formatDate(value)}</span>
        ) : (
          '-'
        ),
    },
    {
      title: '完整度',
      dataIndex: 'completeness',
      width: 130,
      render: (value: number) => (
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${completenessColor(value)}`}
              style={{ width: `${value}%` }}
            />
          </div>
          <span className="font-mono tabular-nums text-xs">{value}%</span>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => (
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(value)}`}
        >
          {RECORD_STATUS_LABELS[value] ?? value}
        </span>
      ),
    },
    { title: '创建人', dataIndex: 'creatorName', width: 100 },
    {
      title: '时间',
      dataIndex: 'createdAt',
      width: 140,
      render: (value: string) => (
        <span className="font-mono tabular-nums text-muted-foreground">
          {formatDateTime(value)}
        </span>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 70,
      fixed: 'right',
      render: (_: unknown, record: RecordListItem) => (
        <Button
          variant="ghost"
          size="sm"
          data-ai-section-type="button"
          aria-label={`删除记录 ${record.title}`}
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

  const handleRowClick = (record: RecordListItem) => {
    setDrawerRecordId(record.id);
    setDrawerOpen(true);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const result = await deleteSiteRecord(deleteTarget.id);
      if (result.status === 'executed') {
        toast.success('已删除');
      } else {
        toast.success('已提交审批，等待超级管理员审批');
      }
      setDeleteTarget(null);
      await loadRecords();
    } catch (err) {
      showApiError(err);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4 p-4" data-ai-section-type="card-list">
      <div>
        <h1 className="text-xl font-semibold">现场记录管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          采集记录的类型识别、完整性检查与补充
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索标题或内容关键字"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value);
              setPage(1);
            }}
            className="pl-8"
          />
        </div>
        <Select
          value={projectId}
          onValueChange={(value) => {
            setProjectId(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-44">
            <SelectValue placeholder="全部项目" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部项目</SelectItem>
            {projects.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={recordType}
          onValueChange={(value) => {
            setRecordType(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {typeConfigs.map((c) => (
              <SelectItem key={c.recordType} value={c.recordType}>
                {c.displayName}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={status}
          onValueChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-32">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value={RECORD_STATUS.COMPLETE}>完整</SelectItem>
            <SelectItem value={RECORD_STATUS.PENDING_SUPPLEMENT}>待补充</SelectItem>
            <SelectItem value={RECORD_STATUS.PENDING_CLASSIFY}>待分类</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading && records.length === 0 ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : records.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <div className="text-sm text-muted-foreground">
            {keyword ? '未找到匹配的记录' : '暂无现场记录，可从移动采集页开始录入'}
          </div>
        </div>
      ) : (
        <div className="rounded-md border border-border bg-card shadow-xs">
          <Table
            columns={columns}
            dataSource={records}
            loading={loading}
            rowKey="id"
            scroll={{ x: 1100, y: 500 }}
            onRow={(record: RecordListItem) => ({
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

      <RecordDetailDrawer
        recordId={drawerRecordId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        typeConfigs={typeConfigs}
        onChanged={() => void loadRecords()}
      />

      <DeleteConfirmDialog
        open={deleteTarget !== null}
        itemLabel="记录"
        itemName={deleteTarget?.title}
        isSuperAdmin={isSuperAdmin}
        submitting={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
};

export default RecordManagementPage;
