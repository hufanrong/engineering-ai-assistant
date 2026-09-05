import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@client/src/components/ui/tabs';
import { getPendingCounts } from '@client/src/api/entity';
import type { PendingCounts } from '@shared/api.interface';
import MergeQueueTab from './MergeQueueTab';
import ConflictTab from './ConflictTab';
import ClassifyTab from './ClassifyTab';
import ApprovalTab from './ApprovalTab';

interface PendingCountBadgeProps {
  value: number;
}

const PendingCountBadge = ({ value }: PendingCountBadgeProps) => (
  <span
    className={`ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full px-1.5 py-0.5 font-mono text-xs tabular-nums ${
      value > 0
        ? 'bg-warning/15 text-[hsl(38_92%_35%)]'
        : 'bg-muted text-muted-foreground'
    }`}
  >
    {value}
  </span>
);

const PendingCenterPage = () => {
  const { id: projectId } = useParams<{ id: string }>();
  const [counts, setCounts] = useState<PendingCounts>({
    mergeQueueCount: 0,
    conflictCount: 0,
    classifyCount: 0,
    approvalCount: 0,
  });

  const refreshCounts = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await getPendingCounts(projectId);
      setCounts(data);
    } catch {
      /* 计数失败不阻塞列表展示 */
    }
  }, [projectId]);

  useEffect(() => {
    void refreshCounts();
  }, [refreshCounts]);

  return (
    <div className="space-y-4 p-4" data-ai-section-type="card-list">
      <div>
        <h1 className="text-xl font-semibold">待确认中心</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          实体归并、版本冲突、待分类记录与高危操作审批队列
        </p>
      </div>

      <Tabs defaultValue="merge" className="w-full">
        <TabsList>
          <TabsTrigger value="merge">
            实体归并
            <PendingCountBadge value={counts.mergeQueueCount} />
          </TabsTrigger>
          <TabsTrigger value="conflict">
            版本冲突
            <PendingCountBadge value={counts.conflictCount} />
          </TabsTrigger>
          <TabsTrigger value="classify">
            待分类记录
            <PendingCountBadge value={counts.classifyCount} />
          </TabsTrigger>
          <TabsTrigger value="approval">
            审批队列
            <PendingCountBadge value={counts.approvalCount} />
          </TabsTrigger>
        </TabsList>
        <TabsContent value="merge" className="mt-4">
          <MergeQueueTab projectId={projectId ?? ''} onOperated={refreshCounts} />
        </TabsContent>
        <TabsContent value="conflict" className="mt-4">
          <ConflictTab projectId={projectId ?? ''} onOperated={refreshCounts} />
        </TabsContent>
        <TabsContent value="classify" className="mt-4">
          <ClassifyTab projectId={projectId ?? ''} onOperated={refreshCounts} />
        </TabsContent>
        <TabsContent value="approval" className="mt-4">
          <ApprovalTab projectId={projectId ?? ''} onOperated={refreshCounts} />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PendingCenterPage;
