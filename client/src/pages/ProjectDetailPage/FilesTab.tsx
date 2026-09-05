import { useCallback, useEffect, useMemo, useState } from 'react';
import dayjs from 'dayjs';
import { toast } from 'sonner';
import {
  FileAudio,
  FileImage,
  FileSpreadsheet,
  FileText,
  MessageSquare,
  PencilRuler,
  Trash2,
} from 'lucide-react';

import {
  Table,
  type TableColumnsType,
} from '@lark-apaas/client-toolkit/antd-table';
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
import DeleteConfirmDialog from '@client/src/components/DeleteConfirmDialog';
import { useIsSuperAdmin } from '@client/src/hooks/use-permission';
import { deleteFile, listFiles } from '@client/src/api/file';
import type { FileListItem, WorkshopSummary } from '@shared/api.interface';
import { FILE_TYPE, PARSE_STATUS_LABELS } from '@shared/api.interface';
import FileDetailSheet from './FileDetailSheet';

interface FilesTabProps {
  projectId: string;
  workshops: WorkshopSummary[];
}

const FILE_TYPE_ICONS: Record<string, React.ReactNode> = {
  pdf: <FileText className="h-4 w-4 text-muted-foreground" />,
  docx: <FileText className="h-4 w-4 text-muted-foreground" />,
  xlsx: <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />,
  txt: <FileText className="h-4 w-4 text-muted-foreground" />,
  dwg: <PencilRuler className="h-4 w-4 text-muted-foreground" />,
  image: <FileImage className="h-4 w-4 text-muted-foreground" />,
  audio: <FileAudio className="h-4 w-4 text-muted-foreground" />,
  chat: <MessageSquare className="h-4 w-4 text-muted-foreground" />,
  other: <FileText className="h-4 w-4 text-muted-foreground" />,
};

export function formatFileSize(size: number): string {
  if (size >= 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${size} B`;
}

export function ParseStatusBadge({ status }: { status: string }) {
  const label = PARSE_STATUS_LABELS[status] ?? status;
  if (status === 'processing') {
    return <Badge className="bg-primary/10 text-primary">解析中</Badge>;
  }
  if (status === 'success') {
    return <Badge className="badge-success">解析成功</Badge>;
  }
  if (status === 'failed') {
    return <Badge variant="destructive">解析失败</Badge>;
  }
  return <Badge variant="secondary">{label}</Badge>;
}

function showApiError(err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('无操作权限')) return;
  toast.error(message || '操作失败');
}

const FilesTab = ({ projectId, workshops }: FilesTabProps) => {
  const isSuperAdmin = useIsSuperAdmin();
  const [workshopId, setWorkshopId] = useState('all');
  const [fileType, setFileType] = useState('all');
  const [parseStatus, setParseStatus] = useState('all');
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<FileListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<FileListItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setKeyword(keywordInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [keywordInput]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listFiles(projectId, {
        workshopId: workshopId === 'all' ? undefined : workshopId,
        fileType: fileType === 'all' ? undefined : fileType,
        parseStatus: parseStatus === 'all' ? undefined : parseStatus,
        keyword: keyword || undefined,
        offset: (page - 1) * pageSize,
        limit: pageSize,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch {
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [projectId, workshopId, fileType, parseStatus, keyword, page]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      const result = await deleteFile(deleteTarget.id);
      if (result.status === 'executed') {
        toast.success('已删除');
      } else {
        toast.success('已提交审批，等待超级管理员审批');
      }
      setDeleteTarget(null);
      await load();
    } catch (err) {
      showApiError(err);
    } finally {
      setDeleting(false);
    }
  };

  const columns: TableColumnsType<FileListItem> = useMemo(
    () => [
      {
        title: '文件名',
        dataIndex: 'filename',
        fixed: 'left',
        width: 260,
        render: (name: string, record: FileListItem) => (
          <div className="flex min-w-0 items-center gap-2">
            {FILE_TYPE_ICONS[record.fileType] ?? FILE_TYPE_ICONS.other}
            <span className="truncate">{name}</span>
            {!record.isLatest && (
              <Badge variant="outline" className="shrink-0 text-xs">
                历史版本
              </Badge>
            )}
          </div>
        ),
      },
      {
        title: '类型',
        dataIndex: 'fileType',
        width: 90,
        render: (type: string) => <span className="font-mono text-xs uppercase">{type}</span>,
      },
      {
        title: '大小',
        dataIndex: 'fileSize',
        width: 100,
        render: (size: number) => (
          <span className="font-mono tabular-nums">{formatFileSize(size)}</span>
        ),
      },
      {
        title: '版本',
        dataIndex: 'versionNo',
        width: 80,
        render: (version: number) => (
          <span className="font-mono font-bold tabular-nums">V{version}</span>
        ),
      },
      {
        title: '归属车间',
        dataIndex: 'workshopNames',
        width: 180,
        render: (names: string[]) =>
          names.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {names.map((name) => (
                <Badge key={name} variant="outline" className="text-xs">
                  {name}
                </Badge>
              ))}
            </div>
          ) : (
            <span className="text-xs text-muted-foreground">未归属</span>
          ),
      },
      {
        title: '解析状态',
        dataIndex: 'parseStatus',
        width: 110,
        render: (status: string) => <ParseStatusBadge status={status} />,
      },
      {
        title: '上传人',
        dataIndex: 'creatorName',
        width: 110,
      },
      {
        title: '时间',
        dataIndex: 'createdAt',
        width: 150,
        render: (time: string) => (
          <span className="font-mono text-xs tabular-nums">
            {dayjs(time).format('YYYY-MM-DD HH:mm')}
          </span>
        ),
      },
      {
        title: '操作',
        key: 'action',
        width: 70,
        fixed: 'right',
        render: (_: unknown, record: FileListItem) => (
          <Button
            variant="ghost"
            size="sm"
            data-ai-section-type="button"
            aria-label={`删除文件 ${record.filename}`}
            onClick={(e) => {
              e.stopPropagation();
              setDeleteTarget(record);
            }}
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={workshopId}
          onValueChange={(v) => {
            setPage(1);
            setWorkshopId(v);
          }}
        >
          <SelectTrigger className="w-44">
            <SelectValue placeholder="全部车间" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部车间</SelectItem>
            {workshops.map((ws) => (
              <SelectItem key={ws.id} value={ws.id}>
                {ws.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={fileType}
          onValueChange={(v) => {
            setPage(1);
            setFileType(v);
          }}
        >
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部类型</SelectItem>
            {Object.values(FILE_TYPE).map((type) => (
              <SelectItem key={type} value={type}>
                {type.toUpperCase()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={parseStatus}
          onValueChange={(v) => {
            setPage(1);
            setParseStatus(v);
          }}
        >
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {Object.entries(PARSE_STATUS_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          className="w-56"
          placeholder="搜索文件名关键字"
          value={keywordInput}
          onChange={(e) => {
            setPage(1);
            setKeywordInput(e.target.value);
          }}
        />
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
          共 {total} 个文件
        </span>
      </div>

      <div className="rounded-md border border-border bg-card">
        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey="id"
          scroll={{ x: 1100, y: 500 }}
          onRow={(record: FileListItem) => ({
            onClick: () => setDetailId(record.id),
            style: { cursor: 'pointer' },
          })}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (next: number) => setPage(next),
          }}
        />
      </div>

      <FileDetailSheet fileId={detailId} onClose={() => setDetailId(null)} />

      <DeleteConfirmDialog
        open={deleteTarget !== null}
        itemLabel="文件"
        itemName={deleteTarget?.filename}
        isSuperAdmin={isSuperAdmin}
        submitting={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
};

export default FilesTab;
