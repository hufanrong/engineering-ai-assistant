import { useCallback, useEffect, useState } from 'react';
import dayjs from 'dayjs';
import { RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import {
  Table,
  type TableColumnsType,
} from '@lark-apaas/client-toolkit/antd-table';
import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import { Progress } from '@client/src/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@client/src/components/ui/select';
import { listTasks, retryTask } from '@client/src/api/file';
import type { TaskListItem } from '@shared/api.interface';
import { TASK_STATUS, TASK_STATUS_LABELS, TASK_TYPE_LABELS } from '@shared/api.interface';

interface TasksTabProps {
  projectId: string;
}

function TaskStatusBadge({ status }: { status: string }) {
  if (status === TASK_STATUS.RUNNING) {
    return <Badge className="bg-primary/10 text-primary">执行中</Badge>;
  }
  if (status === TASK_STATUS.SUCCESS) {
    return <Badge className="badge-success">成功</Badge>;
  }
  if (status === TASK_STATUS.FAILED) {
    return <Badge variant="destructive">失败</Badge>;
  }
  return <Badge variant="secondary">{TASK_STATUS_LABELS[status] ?? status}</Badge>;
}

const TasksTab = ({ projectId }: TasksTabProps) => {
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listTasks(projectId, {
        status: status === 'all' ? undefined : status,
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
  }, [projectId, status, page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [load]);

  const handleRetry = async (task: TaskListItem) => {
    setRetryingId(task.id);
    try {
      await retryTask(task.id);
      toast.success('任务已重新入队');
      await load();
    } catch {
      toast.error('重试失败');
    } finally {
      setRetryingId(null);
    }
  };

  const columns: TableColumnsType<TaskListItem> = [
      {
        title: '任务类型',
        dataIndex: 'taskType',
        fixed: 'left',
        width: 110,
        render: (type: string) => TASK_TYPE_LABELS[type] ?? type,
      },
      {
        title: '关联文件',
        dataIndex: 'fileName',
        width: 220,
        render: (name: string | undefined, record: TaskListItem) => (
          <span className="truncate">
            {name ?? record.recordTitle ?? (
              <span className="text-xs text-muted-foreground">-</span>
            )}
          </span>
        ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 90,
        render: (value: string) => <TaskStatusBadge status={value} />,
      },
      {
        title: '进度',
        dataIndex: 'progress',
        width: 140,
        render: (progress: number) => (
          <div className="flex items-center gap-2">
            <Progress value={progress} className="h-1.5 w-20" />
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {progress}%
            </span>
          </div>
        ),
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
        title: '信息',
        dataIndex: 'message',
        width: 240,
        render: (message: string | undefined) =>
          message ? (
            <span className="truncate text-xs text-muted-foreground" title={message}>
              {message}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">-</span>
          ),
      },
      {
        title: '操作',
        key: 'action',
        fixed: 'right',
        width: 90,
        render: (_, record: TaskListItem) =>
          record.status === TASK_STATUS.FAILED ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={retryingId === record.id}
              onClick={() => void handleRetry(record)}
            >
              <RotateCcw className="mr-1 h-3.5 w-3.5" />
              {retryingId === record.id ? '重试中' : '重试'}
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">-</span>
          ),
      },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={status}
          onValueChange={(v) => {
            setPage(1);
            setStatus(v);
          }}
        >
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {Object.entries(TASK_STATUS_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">每 5 秒自动刷新</span>
        <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
          共 {total} 个任务
        </span>
      </div>

      <div className="rounded-md border border-border bg-card">
        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey="id"
          scroll={{ x: 1100, y: 500 }}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: (next: number) => setPage(next),
          }}
        />
      </div>
    </div>
  );
};

export default TasksTab;
