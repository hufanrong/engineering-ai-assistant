import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  Building2,
  ClipboardList,
  Factory,
  FileText,
  Layers,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@client/src/components/ui/card';
import { Skeleton } from '@client/src/components/ui/skeleton';
import {
  getDashboardActivities,
  getDashboardSummary,
  listProjects,
} from '@client/src/api/project';
import type {
  DashboardActivity,
  DashboardSummary,
} from '@shared/api.interface';
import { formatRelativeTime } from '@client/src/utils/time';

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  highlight?: boolean;
  to?: string;
}

const StatCard = ({ label, value, icon, highlight, to }: StatCardProps) => {
  const navigate = useNavigate();
  const body = (
    <CardContent className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className={highlight ? 'text-warning' : 'text-primary'}>{icon}</span>
      </div>
      <div
        className={`mt-2 font-mono text-3xl font-bold tabular-nums ${
          highlight ? 'text-warning' : 'text-foreground'
        }`}
      >
        {value}
      </div>
    </CardContent>
  );
  if (to) {
    return (
      <Card
        data-ai-section-type="card-stat"
        className="cursor-pointer rounded-md shadow-xs transition-colors hover:border-primary/40"
        onClick={() => navigate(to)}
      >
        {body}
      </Card>
    );
  }
  return (
    <Card data-ai-section-type="card-stat" className="rounded-md shadow-xs">
      {body}
    </Card>
  );
};

interface TodoItemProps {
  title: string;
  description: string;
  count: number;
  to?: string;
}

const TodoItem = ({ title, description, count, to }: TodoItemProps) => {
  const body = (
    <>
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-warning/10 text-warning">
          <AlertCircle className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{title}</div>
          <div className="truncate text-xs text-muted-foreground">{description}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge className="badge-warning font-mono tabular-nums">{count}</Badge>
        <ArrowRight className="h-4 w-4 text-muted-foreground" />
      </div>
    </>
  );
  if (!to) {
    return (
      <div
        className="flex items-center justify-between rounded-md border border-border p-3 opacity-60"
        aria-disabled="true"
        title="暂无项目，无法进入审批队列"
      >
        {body}
      </div>
    );
  }
  return (
    <Link
      to={to}
      className="flex items-center justify-between rounded-md border border-border p-3 transition-colors hover:bg-accent"
    >
      {body}
    </Link>
  );
};

const ActivityItem = ({ activity }: { activity: DashboardActivity }) => (
  <div className="flex items-start gap-3 border-b border-border py-3 last:border-b-0">
    <span
      className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
        activity.kind === 'file'
          ? 'bg-primary/10 text-primary'
          : 'bg-success/10 text-success'
      }`}
    >
      {activity.kind === 'file' ? (
        <FileText className="h-3.5 w-3.5" />
      ) : (
        <ClipboardList className="h-3.5 w-3.5" />
      )}
    </span>
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium">{activity.creatorName}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {activity.kind === 'file' ? '上传了' : '创建了'}
        </span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <Link
          to={
            activity.kind === 'file'
              ? `/projects/${activity.projectId}`
              : '/records'
          }
          className="truncate text-sm text-primary hover:underline"
        >
          {activity.title}
        </Link>
        {activity.recordType && (
          <Badge variant="outline" className="shrink-0 text-xs">
            记录
          </Badge>
        )}
      </div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">
        {activity.projectName} · {formatRelativeTime(activity.createdAt)}
      </div>
    </div>
  </div>
);

const DashboardPage = () => {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [activities, setActivities] = useState<DashboardActivity[]>([]);
  const [firstProjectId, setFirstProjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const [summaryData, activitiesData, projectsData] = await Promise.all([
        getDashboardSummary(),
        getDashboardActivities(20),
        listProjects(),
      ]);
      setSummary(summaryData);
      setActivities(activitiesData.items);
      setFirstProjectId(projectsData.items[0]?.id ?? null);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载仪表盘数据失败';
      setError(message);
      toast.error('加载仪表盘数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  if (loading) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-24 w-full" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-4 p-16">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button onClick={() => void loadData()} variant="outline">
          <Loader2 className="mr-1 h-4 w-4" />
          重试
        </Button>
      </div>
    );
  }

  const pendingTotal =
    (summary?.pendingMergeCount ?? 0) +
    (summary?.pendingConflictCount ?? 0) +
    (summary?.pendingClassifyCount ?? 0);

  return (
    <div className="space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">首页仪表盘</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          项目资料收集进展与待办总览
        </p>
      </div>

      <div
        data-ai-section-type="card-stat"
        className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6"
      >
        <StatCard
          label="项目数"
          value={summary?.projectCount ?? 0}
          icon={<Building2 className="h-4 w-4" />}
          to="/projects"
        />
        <StatCard
          label="车间数"
          value={summary?.workshopCount ?? 0}
          icon={<Factory className="h-4 w-4" />}
        />
        <StatCard
          label="文件总数"
          value={summary?.fileCount ?? 0}
          icon={<FileText className="h-4 w-4" />}
        />
        <StatCard
          label="记录数"
          value={summary?.recordCount ?? 0}
          icon={<ClipboardList className="h-4 w-4" />}
        />
        <StatCard
          label="待确认"
          value={pendingTotal}
          icon={<AlertCircle className="h-4 w-4" />}
          highlight
          to="/projects"
        />
        <StatCard
          label="待补充"
          value={summary?.pendingSupplementCount ?? 0}
          icon={<Layers className="h-4 w-4" />}
          highlight
          to="/records?status=pending_supplement"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="rounded-md shadow-xs">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">待办事项</CardTitle>
            <CardDescription>按优先级列出需要人工处理的项</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <TodoItem
              title="待确认实体归并"
              description="编号对齐不确定的实体候选对"
              count={summary?.pendingMergeCount ?? 0}
              to="/projects"
            />
            <TodoItem
              title="待解决版本冲突"
              description="多版本台账字段冲突待选择"
              count={summary?.pendingConflictCount ?? 0}
              to="/projects"
            />
            <TodoItem
              title="待分类记录"
              description="无法自动识别类型的现场记录"
              count={summary?.pendingClassifyCount ?? 0}
              to="/records?status=pending_classify"
            />
            <TodoItem
              title="待补充记录"
              description="缺失关键内容的记录待逐项补充"
              count={summary?.pendingSupplementCount ?? 0}
              to="/records?status=pending_supplement"
            />
            <TodoItem
              title="待审批"
              description="删除、归并等高危操作待超级管理员审批"
              count={summary?.approvalCount ?? 0}
              to={firstProjectId ? `/projects/${firstProjectId}/pending` : undefined}
            />
          </CardContent>
        </Card>

        <Card className="rounded-md shadow-xs">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">最近动态</CardTitle>
            <CardDescription>最近上传的文件与创建的现场记录</CardDescription>
          </CardHeader>
          <CardContent>
            {activities.length === 0 ? (
              <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
                暂无动态，上传文件或创建记录后展示
              </div>
            ) : (
              <div className="max-h-[420px] overflow-y-auto pr-1">
                {activities.map((activity) => (
                  <ActivityItem key={`${activity.kind}-${activity.id}`} activity={activity} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default DashboardPage;
