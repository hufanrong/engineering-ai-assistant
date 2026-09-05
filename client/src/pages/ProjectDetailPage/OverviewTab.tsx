import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Boxes,
  FileQuestion,
  GitBranch,
  KeyRound,
  Network,
} from 'lucide-react';

import { Badge } from '@client/src/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@client/src/components/ui/card';
import type { ProjectDetailInfo } from '@shared/api.interface';
import { formatDateTime } from '@client/src/utils/time';

interface OverviewTabProps {
  detail: ProjectDetailInfo;
}

const QUICK_LINKS = [
  {
    to: 'entities',
    label: '实体管理',
    description: '标准实体与别名体系',
    icon: Boxes,
  },
  {
    to: 'pending',
    label: '待确认中心',
    description: '归并 / 冲突 / 待分类',
    icon: FileQuestion,
  },
  {
    to: 'graph',
    label: '知识图谱',
    description: '实体关系可视化',
    icon: Network,
  },
  {
    to: 'repository',
    label: '资料库连接',
    description: 'Agent 连接信息',
    icon: KeyRound,
  },
];

const OverviewTab = ({ detail }: OverviewTabProps) => {
  const navigate = useNavigate();

  return (
    <div className="space-y-4">
      <Card className="rounded-md shadow-xs">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">项目信息</CardTitle>
          <CardDescription>项目基本信息与创建时间</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <div>
              <div className="text-xs text-muted-foreground">项目名称</div>
              <div className="mt-1 text-sm font-medium">{detail.name}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">项目编号</div>
              <div className="mt-1 font-mono text-sm">{detail.code}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">项目状态</div>
              <div className="mt-1">
                <Badge variant={detail.status === 'active' ? 'default' : 'secondary'}>
                  {detail.status === 'active' ? '进行中' : '已归档'}
                </Badge>
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">创建时间</div>
              <div className="mt-1 font-mono text-sm tabular-nums">
                {formatDateTime(detail.createdAt)}
              </div>
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">项目描述</div>
            <p className="mt-1 min-h-20 text-sm leading-relaxed">
              {detail.description || '暂无描述'}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-md shadow-xs">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">快捷入口</CardTitle>
          <CardDescription>项目级数据管理功能直达</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {QUICK_LINKS.map((link) => {
              const Icon = link.icon;
              return (
                <button
                  key={link.to}
                  type="button"
                  onClick={() => navigate(`/projects/${detail.id}/${link.to}`)}
                  className="flex items-center gap-3 rounded-md border border-border p-3 text-left transition-colors hover:bg-accent"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{link.label}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {link.description}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
            <GitBranch className="h-3.5 w-3.5" />
            上传台账文件后系统将自动解析提取实体并构建关系图谱
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default OverviewTab;
