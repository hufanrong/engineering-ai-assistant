import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  AlertTriangle,
  Check,
  Copy,
  Database,
  FileText,
  Info,
  KeyRound,
  Link2,
  RefreshCw,
  Search,
  Server,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@client/src/components/ui/button';
import { Card, CardContent } from '@client/src/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { getRepositoryInfo, rotateApiKey } from '@client/src/api/repository';
import type { RepositoryInfo } from '@shared/api.interface';

const maskApiKey = (key: string): string => {
  if (key.length <= 12) return key;
  return `${key.slice(0, 8)}••••••••${key.slice(-4)}`;
};

const extractErrorStatus = (error: unknown): number | undefined => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { status?: number } }).response;
    if (response && typeof response.status === 'number') {
      return response.status;
    }
  }
  return undefined;
};

interface ConnectionItem {
  key: string;
  label: string;
  icon: React.ReactNode;
  value: string;
  displayValue: string;
  copied: boolean;
}

const ConnectionRow = ({
  item,
  onCopy,
  extraAction,
}: {
  item: ConnectionItem;
  onCopy: (item: ConnectionItem) => void;
  extraAction?: React.ReactNode;
}) => {
  return (
    <div className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-muted-foreground">
        {item.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-xs text-muted-foreground">{item.label}</div>
        <div className="mt-0.5 truncate font-mono text-sm text-foreground">
          {item.displayValue}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {extraAction}
        <Button
          data-ai-section-type="button"
          variant="ghost"
          size="icon"
          aria-label={`复制${item.label}`}
          onClick={() => onCopy(item)}
        >
          {item.copied ? (
            <Check className="h-4 w-4 text-success" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
};

const StatCard = ({ label, value }: { label: string; value: number }) => (
  <Card className="rounded-md shadow-xs">
    <CardContent className="p-4">
      <div className="text-3xl font-bold font-mono tabular-nums">
        {value.toLocaleString()}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </CardContent>
  </Card>
);

const PlatformLibCard = ({
  label,
  count,
}: {
  label: string;
  count: number;
}) => (
  <Card className="rounded-md shadow-xs">
    <CardContent className="p-4">
      <div className="text-2xl font-bold font-mono tabular-nums">
        {count.toLocaleString()}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </CardContent>
  </Card>
);

const RepositoryInfoPage = () => {
  const { id } = useParams<{ id: string }>();
  const projectId = id ?? '';

  const [info, setInfo] = useState<RepositoryInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorStatus, setErrorStatus] = useState<number | undefined>(
    undefined,
  );
  const [hasError, setHasError] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [rotateOpen, setRotateOpen] = useState(false);
  const [rotating, setRotating] = useState(false);
  const copyTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );

  const loadInfo = useCallback(async () => {
    if (!projectId) {
      setHasError(true);
      setErrorStatus(404);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setHasError(false);
      setErrorStatus(undefined);
      const data = await getRepositoryInfo(projectId);
      setInfo(data);
    } catch (error: unknown) {
      setHasError(true);
      setErrorStatus(extractErrorStatus(error));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  useEffect(() => {
    const timers = copyTimers.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const markCopied = useCallback((key: string) => {
    setCopiedKey(key);
    const existing = copyTimers.current.get(key);
    if (existing) clearTimeout(existing);
    copyTimers.current.set(
      key,
      setTimeout(() => {
        setCopiedKey((current) => (current === key ? null : current));
        copyTimers.current.delete(key);
      }, 1500),
    );
  }, []);

  const handleCopy = useCallback(
    async (item: ConnectionItem) => {
      try {
        await navigator.clipboard.writeText(item.value);
        markCopied(item.key);
        toast.success('已复制');
      } catch {
        toast.error('复制失败，请手动复制');
      }
    },
    [markCopied],
  );

  const handleCopyAll = useCallback(async () => {
    if (!info) return;
    const payload = JSON.stringify(
      {
        projectName: info.projectName,
        apiEndpoint: info.apiEndpoint,
        searchApi: info.searchApi,
        agentApiKey: info.agentApiKey,
        database: info.localPaths.database,
        files: info.localPaths.files,
      },
      null,
      2,
    );
    try {
      await navigator.clipboard.writeText(payload);
      markCopied('__all__');
      toast.success('已复制全部连接信息');
    } catch {
      toast.error('复制失败，请手动复制');
    }
  }, [info, markCopied]);

  const handleRotate = useCallback(async () => {
    if (!info) return;
    setRotating(true);
    try {
      const result = await rotateApiKey(projectId);
      setInfo({ ...info, agentApiKey: result.agentApiKey });
      toast.success('API Key 已重新生成');
      setRotateOpen(false);
    } catch {
      toast.error('重新生成 API Key 失败');
    } finally {
      setRotating(false);
    }
  }, [info, projectId]);

  if (loading) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-4 p-4">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-[388px] w-full" />
        <div className="grid gap-4 md:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i: number) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-12 w-64" />
      </div>
    );
  }

  if (hasError || !info) {
    const isNotFound = errorStatus === 404;
    return (
      <div className="mx-auto max-w-[1200px] p-4">
        <h1 className="text-xl font-semibold">资料库连接信息</h1>
        <div className="mt-8 flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <AlertTriangle className="h-10 w-10 text-destructive" />
          <div className="text-sm text-muted-foreground">
            {isNotFound
              ? '项目不存在或已被删除，请返回项目列表确认'
              : '加载资料库连接信息失败，请稍后重试'}
          </div>
          <Button variant="outline" onClick={() => void loadInfo()}>
            <RefreshCw className="mr-1 h-4 w-4" />
            重试
          </Button>
        </div>
      </div>
    );
  }

  const connectionItems: ConnectionItem[] = [
    {
      key: 'apiEndpoint',
      label: 'API 端点',
      icon: <Server className="h-4 w-4" />,
      value: info.apiEndpoint,
      displayValue: info.apiEndpoint,
      copied: copiedKey === 'apiEndpoint',
    },
    {
      key: 'searchApi',
      label: '检索 API 地址',
      icon: <Search className="h-4 w-4" />,
      value: info.searchApi,
      displayValue: info.searchApi,
      copied: copiedKey === 'searchApi',
    },
    {
      key: 'agentApiKey',
      label: 'Agent API Key',
      icon: <KeyRound className="h-4 w-4" />,
      value: info.agentApiKey,
      displayValue: maskApiKey(info.agentApiKey),
      copied: copiedKey === 'agentApiKey',
    },
    {
      key: 'database',
      label: '本地数据库路径',
      icon: <Database className="h-4 w-4" />,
      value: info.localPaths.database,
      displayValue: info.localPaths.database,
      copied: copiedKey === 'database',
    },
    {
      key: 'files',
      label: '文件存储路径',
      icon: <FileText className="h-4 w-4" />,
      value: info.localPaths.files,
      displayValue: info.localPaths.files,
      copied: copiedKey === 'files',
    },
  ];

  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4">
      <div>
        <h1 className="text-xl font-semibold">资料库连接信息</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {info.projectName} · 将以下信息复制给外部 Agent 使用
        </p>
      </div>

      <Card className="rounded-md shadow-xs">
        <CardContent className="p-0">
          {connectionItems.map((item: ConnectionItem) => (
            <ConnectionRow
              key={item.key}
              item={item}
              onCopy={handleCopy}
              extraAction={
                item.key === 'agentApiKey' ? (
                  <Button
                    data-ai-section-type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setRotateOpen(true)}
                  >
                    <KeyRound className="mr-1 h-4 w-4" />
                    重新生成
                  </Button>
                ) : undefined
              }
            />
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-5">
        <StatCard label="文件数" value={info.stats.fileCount} />
        <StatCard label="任务记录" value={info.stats.taskCount} />
        <StatCard label="实体数" value={info.stats.entityCount} />
        <StatCard label="关系数" value={info.stats.relationshipCount} />
        <StatCard label="记录数" value={info.stats.recordCount} />
      </div>

      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-md border border-border bg-accent px-4 py-3">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="text-sm text-muted-foreground">
            平台级数据在检索时自动融合，全局共享
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <PlatformLibCard label="规范库条数" count={info.platformLib.standardsCount} />
          <PlatformLibCard label="材料库条数" count={info.platformLib.materialsCount} />
          <PlatformLibCard label="工艺库条数" count={info.platformLib.processesCount} />
        </div>
      </div>

      <Button
        data-ai-section-type="button"
        size="lg"
        onClick={() => void handleCopyAll()}
      >
        {copiedKey === '__all__' ? (
          <Check className="mr-2 h-4 w-4" />
        ) : (
          <Link2 className="mr-2 h-4 w-4" />
        )}
        复制全部连接信息
      </Button>

      <Dialog open={rotateOpen} onOpenChange={setRotateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>重新生成 Agent API Key</DialogTitle>
            <DialogDescription>
              重新生成后旧 Key 立即失效，正在使用旧 Key 的外部 Agent
              将无法访问。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRotateOpen(false)}
              disabled={rotating}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleRotate()}
              disabled={rotating}
            >
              {rotating ? '重新生成中...' : '确认重新生成'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default RepositoryInfoPage;
