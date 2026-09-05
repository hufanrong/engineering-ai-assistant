import { useState } from 'react';
import { toast } from 'sonner';
import { AlertTriangle, Check, Tag } from 'lucide-react';

import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { Input } from '@client/src/components/ui/input';
import { Label } from '@client/src/components/ui/label';
import {
  getRecordDetail,
  supplementRecord,
  updateRecord,
} from '@client/src/api/record';
import type { RecordField, RecordTypeConfigItem } from '@shared/api.interface';
import { RECORD_STATUS_LABELS } from '@shared/api.interface';

export interface CaptureResultData {
  recordId: string;
  recordType: string;
  recordTypeName: string;
  typeConfidence: number;
  content: string;
  missingFields: RecordField[];
  completeness: number;
  status: string;
}

interface CaptureResultPanelProps {
  data: CaptureResultData;
  typeConfigs: RecordTypeConfigItem[];
  onDone: () => void;
}

const CaptureResultPanel = ({ data, typeConfigs, onDone }: CaptureResultPanelProps) => {
  const [current, setCurrent] = useState<CaptureResultData>(data);
  const [typeDialogOpen, setTypeDialogOpen] = useState(false);
  const [selectedType, setSelectedType] = useState('');
  const [supplementValues, setSupplementValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const reload = async () => {
    try {
      const detail = await getRecordDetail(current.recordId);
      setCurrent((prev) => ({
        ...prev,
        recordType: detail.recordType,
        recordTypeName: detail.recordTypeName,
        typeConfidence: detail.typeConfidence,
        content: detail.content,
        missingFields: detail.missingFields,
        completeness: detail.completeness,
        status: detail.status,
      }));
    } catch {
      toast.error('刷新记录失败');
    }
  };

  const handleChangeType = async () => {
    if (!selectedType || selectedType === current.recordType) {
      setTypeDialogOpen(false);
      return;
    }
    try {
      await updateRecord(current.recordId, { recordType: selectedType });
      toast.success('记录类型已更新');
      setTypeDialogOpen(false);
      await reload();
    } catch {
      toast.error('更新类型失败');
    }
  };

  const handleSupplement = async () => {
    const supplements = Object.entries(supplementValues)
      .filter(([, value]) => value.trim().length > 0)
      .map(([key, value]) => ({ key, value: value.trim() }));
    if (supplements.length === 0) {
      toast.error('请填写至少一项补充内容');
      return;
    }
    setSubmitting(true);
    try {
      const result = await supplementRecord(current.recordId, { supplements });
      setCurrent((prev) => ({
        ...prev,
        status: result.status,
        completeness: result.completeness,
        missingFields: result.missingFields,
      }));
      setSupplementValues({});
      if (result.completeness >= 100) {
        toast.success('已补充完整');
      } else {
        toast.success('补充内容已提交');
      }
    } catch {
      toast.error('提交补充内容失败');
    } finally {
      setSubmitting(false);
    }
  };

  const complete = current.completeness >= 100;

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-border bg-card p-4 shadow-xs">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-ai-section-type="button"
            onClick={() => {
              setSelectedType(current.recordType);
              setTypeDialogOpen(true);
            }}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium transition-colors hover:border-primary/50 hover:text-primary"
          >
            <Tag className="h-3 w-3" />
            {current.recordTypeName}
            <span className="text-muted-foreground">点击修改</span>
          </button>
          <Badge variant="outline" className="font-mono tabular-nums text-xs">
            置信度 {Math.round(current.typeConfidence * 100)}%
          </Badge>
          <Badge variant="outline" className="text-xs">
            {RECORD_STATUS_LABELS[current.status] ?? current.status}
          </Badge>
        </div>
        <div className="mt-3 whitespace-pre-wrap break-words text-sm">
          {current.content || '未识别到内容'}
        </div>
        <div className="mt-3 flex items-center gap-2">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={`h-full rounded-full ${complete ? 'bg-success' : 'bg-warning'}`}
              style={{ width: `${current.completeness}%` }}
            />
          </div>
          <span className="font-mono tabular-nums text-xs">{current.completeness}%</span>
        </div>
      </div>

      {current.missingFields.length > 0 ? (
        <div className="space-y-3 rounded-md border border-warning/40 bg-warning/10 p-4">
          <div className="flex items-start gap-2 text-sm font-medium">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              还缺 {current.missingFields.length} 项：
              {current.missingFields.map((f) => f.label).join('、')}
            </span>
          </div>
          <div className="space-y-3">
            {current.missingFields.map((field) => (
              <div key={field.key} className="space-y-1.5">
                <Label htmlFor={`cap-sup-${field.key}`}>{field.label}</Label>
                <Input
                  id={`cap-sup-${field.key}`}
                  value={supplementValues[field.key] ?? ''}
                  placeholder={`请输入${field.label}`}
                  onChange={(e) =>
                    setSupplementValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                  }
                />
              </div>
            ))}
            <div className="flex gap-2">
              <Button
                className="flex-1"
                disabled={submitting}
                onClick={() => void handleSupplement()}
              >
                {submitting ? '提交中...' : '去补充'}
              </Button>
              <Button variant="outline" className="flex-1" onClick={onDone}>
                稍后补充
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center gap-2 rounded-md border border-success/40 bg-success/10 p-3 text-sm text-success">
          <Check className="h-4 w-4" />
          资料已完整
        </div>
      )}

      {current.missingFields.length === 0 && (
        <Button className="w-full" onClick={onDone}>
          继续采集
        </Button>
      )}

      <Dialog open={typeDialogOpen} onOpenChange={setTypeDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>选择记录类型</DialogTitle>
            <DialogDescription>确认后将按新类型重新计算完整性</DialogDescription>
          </DialogHeader>
          <div className="grid max-h-72 grid-cols-2 gap-2 overflow-y-auto">
            {typeConfigs.map((config) => (
              <button
                key={config.recordType}
                type="button"
                onClick={() => setSelectedType(config.recordType)}
                className={`rounded-md border p-2 text-left text-sm transition-colors ${
                  selectedType === config.recordType
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:border-primary/40'
                }`}
              >
                {config.displayName}
              </button>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTypeDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleChangeType()}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default CaptureResultPanel;
