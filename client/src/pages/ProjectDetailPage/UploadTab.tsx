import { useEffect, useRef, useState } from 'react';
import { FolderOpen, Loader2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { getDataloom } from '@lark-apaas/client-toolkit/dataloom';
import { getDefaultBucketId } from '@lark-apaas/client-toolkit/tools/storage';
import { logger } from '@lark-apaas/client-toolkit/logger';
import { Badge } from '@client/src/components/ui/badge';
import { Button } from '@client/src/components/ui/button';
import { Checkbox } from '@client/src/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';
import { Progress } from '@client/src/components/ui/progress';
import { createFile, listFiles } from '@client/src/api/file';
import type { CreateFileResponse, WorkshopSummary } from '@shared/api.interface';
import { FILE_SOURCE, FILE_TYPE } from '@shared/api.interface';
import { formatFileSize } from './FilesTab';

interface UploadTabProps {
  projectId: string;
  workshops: WorkshopSummary[];
  onUploaded?: () => void;
}

interface ScanItem {
  key: string;
  file: File;
  duplicated: boolean;
  selected: boolean;
}

type QueueStatus = 'pending' | 'uploading' | 'done' | 'duplicated' | 'error';

interface QueueItem {
  key: string;
  name: string;
  size: number;
  status: QueueStatus;
  message?: string;
}

const EXT_TYPE_MAP: Record<string, string> = {
  pdf: FILE_TYPE.PDF,
  docx: FILE_TYPE.DOCX,
  doc: FILE_TYPE.DOCX,
  xlsx: FILE_TYPE.XLSX,
  xls: FILE_TYPE.XLSX,
  txt: FILE_TYPE.TXT,
  dwg: FILE_TYPE.DWG,
  png: FILE_TYPE.IMAGE,
  jpg: FILE_TYPE.IMAGE,
  jpeg: FILE_TYPE.IMAGE,
  gif: FILE_TYPE.IMAGE,
  webp: FILE_TYPE.IMAGE,
  bmp: FILE_TYPE.IMAGE,
  wav: FILE_TYPE.AUDIO,
  mp3: FILE_TYPE.AUDIO,
  ogg: FILE_TYPE.AUDIO,
  m4a: FILE_TYPE.AUDIO,
};

function detectFileType(filename: string): string {
  const ext = filename.includes('.') ? filename.split('.').pop()!.toLowerCase() : '';
  return EXT_TYPE_MAP[ext] ?? FILE_TYPE.OTHER;
}

async function computeSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte: number) => byte.toString(16).padStart(2, '0'))
    .join('');
}

const UploadTab = ({ projectId, workshops, onUploaded }: UploadTabProps) => {
  const [dragging, setDragging] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [scanItems, setScanItems] = useState<ScanItem[]>([]);
  const [workshopIds, setWorkshopIds] = useState<string[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInputRef.current?.setAttribute('webkitdirectory', '');
  }, []);

  const openScan = async (files: File[]) => {
    if (files.length === 0) {
      return;
    }
    try {
      const existing = await listFiles(projectId, { limit: 100, offset: 0 });
      const existingKeys = new Set(
        existing.items.map((item) => `${item.filename}:${item.fileSize}`),
      );
      const items: ScanItem[] = files.map((file: File, index: number) => ({
        key: `${file.name}-${file.size}-${index}`,
        file,
        duplicated: existingKeys.has(`${file.name}:${file.size}`),
        selected: !existingKeys.has(`${file.name}:${file.size}`),
      }));
      setScanItems(items);
      setScanOpen(true);
    } catch {
      setScanItems(
        files.map((file: File, index: number) => ({
          key: `${file.name}-${file.size}-${index}`,
          file,
          duplicated: false,
          selected: true,
        })),
      );
      setScanOpen(true);
    }
  };

  const handlePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    void openScan(files);
    e.target.value = '';
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    void openScan(files);
  };

  const toggleItem = (key: string, checked: boolean) => {
    setScanItems((prev) =>
      prev.map((item) => (item.key === key ? { ...item, selected: checked } : item)),
    );
  };

  const updateQueueItem = (key: string, patch: Partial<QueueItem>) => {
    setQueue((prev) => prev.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  };

  const uploadOne = async (item: ScanItem): Promise<void> => {
    const { file } = item;
    try {
      const dataloom = await getDataloom();
      const { data, error } = await dataloom.storage
        .from(getDefaultBucketId())
        .uploadFile(file);
      if (error || !data) {
        const reason =
          typeof error === 'object' && error !== null && 'message' in error
            ? String((error as { message?: unknown }).message)
            : '文件存储上传失败';
        throw new Error(reason);
      }
      const sha256 = await computeSha256(file);
      const response: CreateFileResponse = await createFile(projectId, {
        filename: file.name,
        fileUrl: data.download_url,
        fileType: detectFileType(file.name),
        fileSize: file.size,
        sha256,
        workshopIds,
        source: FILE_SOURCE.WEB_UPLOAD,
      });
      if (response.duplicated) {
        toast.info(`「${file.name}」文件已存在，已跳过`);
        updateQueueItem(item.key, { status: 'duplicated', message: '文件已存在，已跳过' });
      } else {
        updateQueueItem(item.key, { status: 'done', message: `已提交为 V${response.versionNo}` });
      }
    } catch (err) {
      logger.error(`上传失败: ${file.name} ${String(err)}`);
      updateQueueItem(item.key, {
        status: 'error',
        message: err instanceof Error ? err.message : '上传失败',
      });
    }
  };

  const handleConfirmUpload = async () => {
    const selected = scanItems.filter((item) => item.selected);
    if (selected.length === 0) {
      toast.error('请至少勾选一个文件');
      return;
    }
    setScanOpen(false);
    setQueue(
      selected.map((item) => ({
        key: item.key,
        name: item.file.name,
        size: item.file.size,
        status: 'pending' as QueueStatus,
      })),
    );
    setUploading(true);
    for (const item of selected) {
      updateQueueItem(item.key, { status: 'uploading' });
      await uploadOne(item);
    }
    setUploading(false);
    if (onUploaded) {
      onUploaded();
    }
  };

  return (
    <div className="space-y-4">
      <div
        className={`flex h-56 flex-col items-center justify-center gap-3 rounded-md border-2 border-dashed transition-colors ${
          dragging ? 'border-primary bg-primary/5' : 'border-border bg-card'
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <Upload className="h-10 w-10 text-muted-foreground" />
        <div className="text-sm text-muted-foreground">
          拖拽文件到此处，或点击下方按钮选择
        </div>
        <div className="flex gap-2">
          <Button variant="outline" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
            <Upload className="mr-1 h-4 w-4" />
            选择文件
          </Button>
          <Button
            variant="outline"
            disabled={uploading}
            onClick={() => folderInputRef.current?.click()}
          >
            <FolderOpen className="mr-1 h-4 w-4" />
            上传文件夹
          </Button>
        </div>
      </div>

      <input ref={fileInputRef} type="file" multiple hidden onChange={handlePick} />
      <input ref={folderInputRef} type="file" multiple hidden onChange={handlePick} />

      {queue.length > 0 && (
        <div className="rounded-md border border-border bg-card p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-semibold">上传队列</span>
            {uploading && (
              <span className="flex items-center gap-1 text-xs text-primary">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                上传中
              </span>
            )}
          </div>
          <div className="space-y-2">
            {queue.map((item) => (
              <div
                key={item.key}
                className="flex items-center gap-3 rounded-md border border-border px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm">{item.name}</span>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                      {formatFileSize(item.size)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5">
                    <Progress
                      value={item.status === 'pending' ? 0 : item.status === 'uploading' ? 50 : 100}
                      className="h-1.5"
                    />
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {item.status === 'pending' && '等待上传'}
                    {item.status === 'uploading' && '上传中'}
                    {item.status === 'done' && (item.message ?? '已提交')}
                    {item.status === 'duplicated' && (
                      <span className="text-warning">{item.message ?? '重复跳过'}</span>
                    )}
                    {item.status === 'error' && (
                      <span className="text-destructive">{item.message ?? '上传失败'}</span>
                    )}
                  </div>
                </div>
                <div className="shrink-0">
                  {item.status === 'done' && (
                    <Badge className="badge-success">已提交</Badge>
                  )}
                  {item.status === 'duplicated' && (
                    <Badge className="badge-warning">重复</Badge>
                  )}
                  {item.status === 'error' && <Badge variant="destructive">失败</Badge>}
                  {item.status === 'uploading' && (
                    <Badge className="bg-primary/10 text-primary">上传中</Badge>
                  )}
                  {item.status === 'pending' && <Badge variant="secondary">等待</Badge>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <Dialog open={scanOpen} onOpenChange={setScanOpen}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>确认上传文件（{scanItems.length}）</DialogTitle>
            <DialogDescription>
              已存在同名且同大小的文件默认不勾选，可手动调整
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-1.5">
            {scanItems.map((item) => (
              <label
                key={item.key}
                className="flex cursor-pointer items-center gap-3 rounded-md border border-border px-3 py-2 hover:bg-accent"
              >
                <Checkbox
                  checked={item.selected}
                  onCheckedChange={(checked) => toggleItem(item.key, checked === true)}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{item.file.name}</span>
                <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                  {formatFileSize(item.file.size)}
                </span>
                <span className="w-14 shrink-0 text-right font-mono text-xs uppercase text-muted-foreground">
                  {detectFileType(item.file.name)}
                </span>
                {item.duplicated && (
                  <Badge className="badge-warning shrink-0">重复</Badge>
                )}
              </label>
            ))}
          </div>

          <div>
            <div className="mb-2 text-sm font-semibold">归属车间（可多选）</div>
            {workshops.length === 0 ? (
              <p className="text-xs text-muted-foreground">项目暂无车间，将不归属任何车间</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {workshops.map((ws) => (
                  <label
                    key={ws.id}
                    className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
                  >
                    <Checkbox
                      checked={workshopIds.includes(ws.id)}
                      onCheckedChange={(checked) => {
                        setWorkshopIds((prev) =>
                          checked === true
                            ? [...prev, ws.id]
                            : prev.filter((id) => id !== ws.id),
                        );
                      }}
                    />
                    {ws.name}
                  </label>
                ))}
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setScanOpen(false)}>
              取消
            </Button>
            <Button
              disabled={uploading || scanItems.every((item) => !item.selected)}
              onClick={() => void handleConfirmUpload()}
            >
              {uploading ? '上传中...' : `开始上传（${scanItems.filter((i) => i.selected).length}）`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default UploadTab;
