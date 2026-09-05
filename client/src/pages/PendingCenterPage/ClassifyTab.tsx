import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@client/src/components/ui/select';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { getRecordTypeConfigs, listSiteRecords, updateRecord } from '@client/src/api/record';
import type {
  RecordListItem,
  RecordTypeConfigItem,
} from '@shared/api.interface';
import { formatDateTime } from '@client/src/utils/time';

const PAGE_SIZE = 20;

interface ClassifyTabProps {
  projectId: string;
  onOperated: () => void;
}

const ClassifyTab = ({ projectId, onOperated }: ClassifyTabProps) => {
  const [records, setRecords] = useState<RecordListItem[]>([]);
  const [typeConfigs, setTypeConfigs] = useState<RecordTypeConfigItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [operatingId, setOperatingId] = useState<string | null>(null);

  const loadRecords = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSiteRecords({
        projectId,
        status: 'pending_classify',
        offset: 0,
        limit: PAGE_SIZE,
      });
      setRecords(data.items);
    } catch {
      toast.error('加载待分类记录失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadRecords();
    void (async () => {
      try {
        const configData = await getRecordTypeConfigs();
        setTypeConfigs(configData.items);
      } catch {
        toast.error('加载类型配置失败');
      }
    })();
  }, [loadRecords]);

  const handleAssignType = async (recordId: string, recordType: string) => {
    setOperatingId(recordId);
    try {
      await updateRecord(recordId, { recordType });
      toast.success('记录类型已更新');
      setRecords((prev) => prev.filter((r) => r.id !== recordId));
      onOperated();
    } catch {
      toast.error('更新记录类型失败');
    } finally {
      setOperatingId(null);
    }
  };

  if (loading && records.length === 0) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
        <div className="text-sm text-muted-foreground">暂无待分类记录</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {records.map((record) => {
        const operating = operatingId === record.id;
        return (
          <div
            key={record.id}
            className={`flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-card p-3 shadow-xs transition-opacity ${
              operating ? 'opacity-50' : ''
            }`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{record.title}</span>
                <Badge variant="outline" className="shrink-0">
                  待分类
                </Badge>
              </div>
              <div className="mt-1 font-mono text-xs tabular-nums text-muted-foreground">
                {formatDateTime(record.createdAt)}
                {record.workshopName ? ` · ${record.workshopName}` : ''}
              </div>
            </div>
            <Select
              value=""
              onValueChange={(value: string) => {
                if (value) void handleAssignType(record.id, value);
              }}
              disabled={operating}
            >
              <SelectTrigger className="w-44">
                <SelectValue placeholder="选择记录类型" />
              </SelectTrigger>
              <SelectContent>
                {typeConfigs.map((config) => (
                  <SelectItem key={config.recordType} value={config.recordType}>
                    {config.displayName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      })}
    </div>
  );
};

export default ClassifyTab;
