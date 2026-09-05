import { useEffect, useState } from 'react';
import { ChevronDown, Factory } from 'lucide-react';

import { Button } from '@client/src/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { listProjects, listWorkshops } from '@client/src/api/project';
import type { ProjectSummaryItem, WorkshopSummary } from '@shared/api.interface';

interface ProjectSelectorProps {
  projectId: string | null;
  workshopId: string | null;
  onChange: (projectId: string, workshopId: string | null) => void;
}

const ProjectSelector = ({ projectId, workshopId, onChange }: ProjectSelectorProps) => {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummaryItem[]>([]);
  const [workshops, setWorkshops] = useState<WorkshopSummary[]>([]);
  const [pendingProjectId, setPendingProjectId] = useState<string>('');
  const [pendingWorkshopId, setPendingWorkshopId] = useState<string | null>(null);
  const [loadingWorkshops, setLoadingWorkshops] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    void (async () => {
      try {
        const data = await listProjects();
        setProjects(data.items);
      } catch {
        setProjects([]);
      }
    })();
  }, [open]);

  useEffect(() => {
    if (!open || !pendingProjectId) {
      return;
    }
    void (async () => {
      setLoadingWorkshops(true);
      try {
        const data = await listWorkshops(pendingProjectId);
        setWorkshops(data.items);
      } catch {
        setWorkshops([]);
      } finally {
        setLoadingWorkshops(false);
      }
    })();
  }, [open, pendingProjectId]);

  const projectName =
    projects.find((p) => p.id === projectId)?.name ?? (projectId ? '当前项目' : '选择项目');
  const workshopName = workshops.find((w) => w.id === workshopId)?.name;

  const handleOpen = () => {
    setPendingProjectId(projectId ?? '');
    setPendingWorkshopId(workshopId);
    setOpen(true);
  };

  const handleConfirm = () => {
    if (!pendingProjectId) {
      return;
    }
    onChange(pendingProjectId, pendingWorkshopId);
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        data-ai-section-type="button"
        onClick={handleOpen}
        className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-card px-4 py-3 text-left shadow-xs"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-sm font-semibold">
            <Factory className="h-4 w-4 shrink-0 text-primary" />
            <span className="truncate">{projectName}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {workshopName ?? '未指定车间'}
          </div>
        </div>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>选择项目与车间</DialogTitle>
            <DialogDescription>采集记录将归属到所选项目</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid max-h-52 grid-cols-2 gap-2 overflow-y-auto">
              {projects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    setPendingProjectId(p.id);
                    setPendingWorkshopId(null);
                  }}
                  className={`rounded-md border p-2 text-left text-sm transition-colors ${
                    pendingProjectId === p.id
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:border-primary/40'
                  }`}
                >
                  <div className="truncate">{p.name}</div>
                  <div className="mt-0.5 font-mono text-xs text-muted-foreground">{p.code}</div>
                </button>
              ))}
              {projects.length === 0 && (
                <div className="col-span-2 rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                  暂无可选项目
                </div>
              )}
            </div>
            {pendingProjectId && (
              <div>
                <div className="mb-2 text-xs font-medium text-muted-foreground">车间（可选）</div>
                {loadingWorkshops ? (
                  <div className="py-2 text-center text-xs text-muted-foreground">加载车间中...</div>
                ) : workshops.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
                    该项目暂无车间
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {workshops.map((w) => (
                      <button
                        key={w.id}
                        type="button"
                        onClick={() =>
                          setPendingWorkshopId(pendingWorkshopId === w.id ? null : w.id)
                        }
                        className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                          pendingWorkshopId === w.id
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border hover:border-primary/40'
                        }`}
                      >
                        {w.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button disabled={!pendingProjectId} onClick={handleConfirm}>
              确认
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default ProjectSelector;
