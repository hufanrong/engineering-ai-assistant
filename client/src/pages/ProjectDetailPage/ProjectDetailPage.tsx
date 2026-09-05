import { Link, useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  Boxes,
  ClipboardList,
  FileText,
  Factory,
  Layers,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import {
  Card,
  CardContent,
} from '@client/src/components/ui/card';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@client/src/components/ui/tabs';
import { useProjectDetail } from './useProjectDetail';
import OverviewTab from './OverviewTab';
import WorkshopTab from './WorkshopTab';
import FilesTab from './FilesTab';
import UploadTab from './UploadTab';
import TasksTab from './TasksTab';

interface StatItemProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  highlight?: boolean;
  to?: string;
}

const StatItem = ({ label, value, icon, highlight, to }: StatItemProps) => {
  const navigate = useNavigate();
  return (
    <Card
      data-ai-section-type="card-stat"
      className={`cursor-pointer rounded-md shadow-xs transition-colors hover:border-primary/40 ${
        to ? '' : 'cursor-default'
      }`}
      onClick={to ? () => navigate(to) : undefined}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
          <span className={highlight ? 'text-warning' : 'text-primary'}>{icon}</span>
        </div>
        <div
          className={`mt-2 font-mono text-2xl font-bold tabular-nums ${
            highlight ? 'text-warning' : 'text-foreground'
          }`}
        >
          {value}
        </div>
      </CardContent>
    </Card>
  );
};

const ProjectDetailPage = () => {
  const { detail, statistics, workshops, loading, error, reloadStatistics, reloadWorkshops } =
    useProjectDetail();
  const navigate = useNavigate();

  if (loading) {
    return (
      <div className="space-y-4 p-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex flex-col items-center gap-4 p-16">
        <p className="text-sm text-muted-foreground">{error ?? '项目不存在'}</p>
        <Button variant="outline" onClick={() => navigate('/projects')}>
          <ArrowLeft className="mr-1 h-4 w-4" />
          返回项目列表
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => navigate('/projects')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-semibold">{detail.name}</h1>
            <Badge variant="outline" className="font-mono">
              {detail.code}
            </Badge>
            {detail.status === 'archived' && (
              <Badge variant="secondary">已归档</Badge>
            )}
          </div>
          <p className="mt-1 line-clamp-1 text-sm text-muted-foreground">
            {detail.description || '暂无描述'}
          </p>
        </div>
      </div>

      <div
        data-ai-section-type="card-stat"
        className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6"
      >
        <StatItem
          label="车间数"
          value={statistics?.workshopCount ?? 0}
          icon={<Factory className="h-4 w-4" />}
        />
        <StatItem
          label="文件数"
          value={statistics?.fileCount ?? 0}
          icon={<FileText className="h-4 w-4" />}
        />
        <StatItem
          label="记录数"
          value={statistics?.recordCount ?? 0}
          icon={<ClipboardList className="h-4 w-4" />}
        />
        <StatItem
          label="实体数"
          value={statistics?.entityCount ?? 0}
          icon={<Boxes className="h-4 w-4" />}
        />
        <StatItem
          label="待确认数"
          value={statistics?.pendingMergeCount ?? 0}
          icon={<AlertCircle className="h-4 w-4" />}
          highlight
          to={`/projects/${detail.id}/pending`}
        />
        <StatItem
          label="待补充数"
          value={statistics?.pendingSupplementCount ?? 0}
          icon={<Layers className="h-4 w-4" />}
          highlight
          to={`/records?projectId=${detail.id}&status=pending_supplement`}
        />
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">项目概览</TabsTrigger>
          <TabsTrigger value="workshops">车间管理</TabsTrigger>
          <TabsTrigger value="files">文件管理</TabsTrigger>
          <TabsTrigger value="upload">上传中心</TabsTrigger>
          <TabsTrigger value="tasks">后台任务</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-4">
          <OverviewTab detail={detail} />
        </TabsContent>
        <TabsContent value="workshops" className="mt-4">
          <WorkshopTab
            projectId={detail.id}
            workshops={workshops}
            loading={loading}
            onChanged={async () => {
              await reloadWorkshops();
            }}
          />
        </TabsContent>
        <TabsContent value="files" className="mt-4">
          <FilesTab projectId={detail.id} workshops={workshops} />
        </TabsContent>
        <TabsContent value="upload" className="mt-4">
          <UploadTab
            projectId={detail.id}
            workshops={workshops}
            onUploaded={() => void reloadStatistics()}
          />
        </TabsContent>
        <TabsContent value="tasks" className="mt-4">
          <TasksTab projectId={detail.id} />
        </TabsContent>
      </Tabs>

      <div className="text-xs text-muted-foreground">
        更多入口：
        <Link to={`/projects/${detail.id}/entities`} className="text-primary hover:underline">
          实体管理
        </Link>
        ·
        <Link to={`/projects/${detail.id}/pending`} className="text-primary hover:underline">
          待确认中心
        </Link>
        ·
        <Link to={`/projects/${detail.id}/graph`} className="text-primary hover:underline">
          知识图谱
        </Link>
        ·
        <Link to={`/projects/${detail.id}/repository`} className="text-primary hover:underline">
          资料库连接信息
        </Link>
      </div>
    </div>
  );
};

export default ProjectDetailPage;
