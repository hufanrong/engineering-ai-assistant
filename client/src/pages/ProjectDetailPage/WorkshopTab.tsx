import { useState } from 'react';
import { Factory, FileText, ClipboardList, Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@client/src/components/ui/badge';
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
import { Input } from '@client/src/components/ui/input';
import { Label } from '@client/src/components/ui/label';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { Textarea } from '@client/src/components/ui/textarea';
import {
  createWorkshop,
  deleteWorkshop,
  updateWorkshop,
} from '@client/src/api/project';
import type { WorkshopSummary } from '@shared/api.interface';

interface WorkshopTabProps {
  projectId: string;
  workshops: WorkshopSummary[];
  loading: boolean;
  onChanged: () => Promise<void>;
}

interface WorkshopForm {
  name: string;
  code: string;
  description: string;
}

const EMPTY_FORM: WorkshopForm = { name: '', code: '', description: '' };

const WorkshopTab = ({ projectId, workshops, loading, onChanged }: WorkshopTabProps) => {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<WorkshopSummary | null>(null);
  const [form, setForm] = useState<WorkshopForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WorkshopSummary | null>(null);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = (workshop: WorkshopSummary) => {
    setEditing(workshop);
    setForm({
      name: workshop.name,
      code: workshop.code,
      description: workshop.description ?? '',
    });
    setDialogOpen(true);
  };

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.code.trim()) {
      toast.error('请填写车间名称与车间编号');
      return;
    }
    setSubmitting(true);
    try {
      if (editing) {
        await updateWorkshop(editing.id, {
          name: form.name.trim(),
          code: form.code.trim(),
          description: form.description.trim() || undefined,
        });
        toast.success('车间已更新');
      } else {
        await createWorkshop(projectId, {
          name: form.name.trim(),
          code: form.code.trim(),
          description: form.description.trim() || undefined,
        });
        toast.success('车间创建成功');
      }
      setDialogOpen(false);
      await onChanged();
    } catch {
      toast.error(editing ? '更新车间失败' : '创建车间失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) {
      return;
    }
    setSubmitting(true);
    try {
      await deleteWorkshop(deleteTarget.id);
      toast.success(`车间「${deleteTarget.name}」已删除`);
      setDeleteTarget(null);
      await onChanged();
    } catch {
      toast.error('删除车间失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          车间是文件、记录、实体的归属单元
        </p>
        <Button onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" />
          新建车间
        </Button>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : workshops.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <Factory className="h-10 w-10 text-muted-foreground" />
          <div className="text-sm text-muted-foreground">
            暂无车间，点击右上角新建车间开始
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {workshops.map((workshop) => (
            <Card
              key={workshop.id}
              data-ai-section-type="card-list"
              className="rounded-md shadow-xs"
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-base font-semibold">
                      {workshop.name}
                    </div>
                    <Badge variant="outline" className="mt-1 font-mono text-xs">
                      {workshop.code}
                    </Badge>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => openEdit(workshop)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => setDeleteTarget(workshop)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                <div className="mt-2 line-clamp-2 min-h-10 text-xs text-muted-foreground">
                  {workshop.description || '暂无描述'}
                </div>
                <div className="mt-3 flex items-center gap-4 border-t border-border pt-3 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1.5">
                    <FileText className="h-4 w-4" />
                    <span className="font-mono tabular-nums text-foreground">
                      {workshop.fileCount}
                    </span>
                    文件
                  </span>
                  <span className="flex items-center gap-1.5">
                    <ClipboardList className="h-4 w-4" />
                    <span className="font-mono tabular-nums text-foreground">
                      {workshop.recordCount}
                    </span>
                    记录
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑车间' : '新建车间'}</DialogTitle>
            <DialogDescription>
              车间作为文件、记录、实体的归属单元
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="workshop-name">车间名称</Label>
              <Input
                id="workshop-name"
                placeholder="如：烧成车间"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="workshop-code">车间编号</Label>
              <Input
                id="workshop-code"
                placeholder="如：WS-01"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="workshop-desc">车间描述</Label>
              <Textarea
                id="workshop-desc"
                placeholder="车间简介（可选）"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleSubmit()} disabled={submitting}>
              {submitting ? '保存中...' : editing ? '保存' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>确认删除车间</DialogTitle>
            <DialogDescription>
              将删除车间「{deleteTarget?.name}」，其下文件与记录的归属关联将被移除，该操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button variant="destructive" onClick={() => void handleDelete()} disabled={submitting}>
              {submitting ? '删除中...' : '删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default WorkshopTab;
