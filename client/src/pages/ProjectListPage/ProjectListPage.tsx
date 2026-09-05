import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Archive,
  Building2,
  ClipboardList,
  Factory,
  FileText,
  Pencil,
  Plus,
  Search,
  Trash2,
} from 'lucide-react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@client/src/components/ui/select';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { Textarea } from '@client/src/components/ui/textarea';
import {
  createProject,
  deleteProject,
  getProjectDetail,
  listProjects,
  updateProject,
} from '@client/src/api/project';
import { useIsProjectManager } from '@client/src/hooks/use-permission';
import type { ProjectSummaryItem } from '@shared/api.interface';
import { formatDate } from '@client/src/utils/time';

const showApiError = (err: unknown): void => {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('无操作权限')) return;
  toast.error(message || '操作失败');
};

interface ProjectCardProps {
  project: ProjectSummaryItem;
  canManage: boolean;
  onEdit: (project: ProjectSummaryItem) => void;
  onDelete: (project: ProjectSummaryItem) => void;
}

const ProjectCard = ({ project, canManage, onEdit, onDelete }: ProjectCardProps) => {
  const navigate = useNavigate();
  return (
    <Card
      data-ai-section-type="card-list"
      className="cursor-pointer rounded-md shadow-xs transition-colors hover:border-primary/40"
      onClick={() => navigate(`/projects/${project.id}`)}
    >
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-base font-semibold">{project.name}</div>
            <div className="mt-1 flex items-center gap-2">
              <Badge variant="outline" className="font-mono text-xs">
                {project.code}
              </Badge>
              {project.status === 'archived' && (
                <Badge variant="secondary" className="text-xs">
                  已归档
                </Badge>
              )}
            </div>
          </div>
          {project.pendingCount > 0 && (
            <Badge className="badge-warning shrink-0 font-mono tabular-nums">
              {project.pendingCount} 项待确认
            </Badge>
          )}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Factory className="h-4 w-4" />
            <span className="font-mono tabular-nums text-foreground">
              {project.workshopCount}
            </span>
            车间
          </div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <FileText className="h-4 w-4" />
            <span className="font-mono tabular-nums text-foreground">
              {project.fileCount}
            </span>
            文件
          </div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <ClipboardList className="h-4 w-4" />
            <span className="font-mono tabular-nums text-foreground">
              {project.recordCount}
            </span>
            记录
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between">
          <div className="text-xs text-muted-foreground">
            创建于 {formatDate(project.createdAt)}
          </div>
          {canManage && (
            <div
              className="flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-muted-foreground"
                onClick={() => onEdit(project)}
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-destructive hover:text-destructive"
                onClick={() => onDelete(project)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

const ProjectListPage = () => {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('all');
  const [projects, setProjects] = useState<ProjectSummaryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', code: '', description: '' });
  const [editOpen, setEditOpen] = useState(false);
  const [editSaving, setEditSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ name: '', code: '', description: '' });
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummaryItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  const isManager = useIsProjectManager();

  const loadProjects = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listProjects(
        keyword || undefined,
        status === 'all' ? undefined : status,
      );
      setProjects(data.items);
    } catch {
      toast.error('加载项目列表失败');
    } finally {
      setLoading(false);
    }
  }, [keyword, status]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void loadProjects();
    }, 300);
    return () => clearTimeout(timer);
  }, [loadProjects]);

  const handleOpenEdit = async (project: ProjectSummaryItem) => {
    setEditingId(project.id);
    setEditForm({ name: project.name, code: project.code, description: '' });
    setEditOpen(true);
    try {
      const detail = await getProjectDetail(project.id);
      setEditForm({
        name: detail.name,
        code: detail.code,
        description: detail.description ?? '',
      });
    } catch (err) {
      showApiError(err);
    }
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    if (!editForm.name.trim() || !editForm.code.trim()) {
      toast.error('请填写项目名称与项目编号');
      return;
    }
    setEditSaving(true);
    try {
      await updateProject(editingId, {
        name: editForm.name.trim(),
        code: editForm.code.trim(),
        description: editForm.description.trim(),
      });
      toast.success('项目已更新');
      setEditOpen(false);
      setEditingId(null);
      await loadProjects();
    } catch (err) {
      showApiError(err);
    } finally {
      setEditSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteProject(deleteTarget.id);
      toast.success('项目已删除');
      setDeleteTarget(null);
      await loadProjects();
    } catch (err) {
      showApiError(err);
    } finally {
      setDeleting(false);
    }
  };

  const handleCreate = async () => {
    if (!form.name.trim() || !form.code.trim()) {
      toast.error('请填写项目名称与项目编号');
      return;
    }
    setCreating(true);
    try {
      const created = await createProject({
        name: form.name.trim(),
        code: form.code.trim(),
        description: form.description.trim() || undefined,
      });
      toast.success('项目创建成功');
      setCreateOpen(false);
      setForm({ name: '', code: '', description: '' });
      navigate(`/projects/${created.id}`);
    } catch {
      toast.error('创建项目失败');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">项目管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            以车间为核心组织单元的项目集合
          </p>
        </div>
        {isManager && (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />
            新建项目
          </Button>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索项目名称或编号"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="项目状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="active">进行中</SelectItem>
            <SelectItem value="archived">已归档</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-44" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border">
          <Building2 className="h-10 w-10 text-muted-foreground" />
          <div className="text-sm text-muted-foreground">
            {keyword ? '未找到匹配的项目' : '暂无项目，点击右上角新建项目开始'}
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              canManage={isManager}
              onEdit={(p) => void handleOpenEdit(p)}
              onDelete={setDeleteTarget}
            />
          ))}
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>
              创建后自动生成 Agent API Key，可在资料库连接信息页查看
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="project-name">项目名称</Label>
              <Input
                id="project-name"
                placeholder="如：某水泥厂生产线项目"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-code">项目编号</Label>
              <Input
                id="project-code"
                placeholder="如：P-2026-001"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-desc">项目描述</Label>
              <Textarea
                id="project-desc"
                placeholder="项目简介（可选）"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleCreate()} disabled={creating}>
              {creating ? '创建中...' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>编辑项目</DialogTitle>
            <DialogDescription>修改项目基本信息</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-project-name">项目名称</Label>
              <Input
                id="edit-project-name"
                placeholder="如：某水泥厂生产线项目"
                value={editForm.name}
                onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-project-code">项目编号</Label>
              <Input
                id="edit-project-code"
                placeholder="如：P-2026-001"
                value={editForm.code}
                onChange={(e) => setEditForm({ ...editForm, code: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-project-desc">项目描述</Label>
              <Textarea
                id="edit-project-desc"
                placeholder="项目简介（可选）"
                value={editForm.description}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleUpdate()} disabled={editSaving}>
              {editSaving ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除项目</DialogTitle>
            <DialogDescription>
              确定要删除「{deleteTarget?.name}」吗？将级联删除项目下全部车间、文件、记录、实体等数据，不可恢复。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDelete()}
              disabled={deleting}
            >
              {deleting ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ProjectListPage;
