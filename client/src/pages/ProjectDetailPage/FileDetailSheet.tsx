import { useEffect, useState } from 'react';
import dayjs from 'dayjs';

import { Badge } from '@client/src/components/ui/badge';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@client/src/components/ui/sheet';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { getFileDetail } from '@client/src/api/file';
import type { FileDetail } from '@shared/api.interface';
import { ParseStatusBadge, formatFileSize } from './FilesTab';

interface FileDetailSheetProps {
  fileId: string | null;
  onClose: () => void;
}

const FileDetailSheet = ({ fileId, onClose }: FileDetailSheetProps) => {
  const [detail, setDetail] = useState<FileDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!fileId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    getFileDetail(fileId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [fileId]);

  return (
    <Sheet open={fileId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-[480px] overflow-y-auto sm:max-w-[480px]">
        <SheetHeader>
          <SheetTitle className="truncate pr-6">{detail?.filename ?? '文件详情'}</SheetTitle>
          <SheetDescription>文件基础信息、版本历史与关联实体</SheetDescription>
        </SheetHeader>
        {loading || !detail ? (
          <div className="space-y-3 px-4 pb-8">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        ) : (
          <div className="space-y-5 px-4 pb-8">
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">类型</span>
                <span className="font-mono uppercase">{detail.fileType}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">大小</span>
                <span className="font-mono tabular-nums">
                  {formatFileSize(detail.fileSize)}
                </span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-muted-foreground">当前版本</span>
                <span className="font-mono font-bold tabular-nums">V{detail.versionNo}</span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="shrink-0 text-muted-foreground">SHA-256</span>
                <span className="break-all text-right font-mono text-xs">
                  {detail.sha256}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">解析状态</span>
                <ParseStatusBadge status={detail.parseStatus} />
              </div>
              {detail.parseStatus === 'failed' && detail.parseError && (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
                  {detail.parseError}
                </div>
              )}
            </div>

            <div>
              <div className="mb-2 text-sm font-semibold">关联车间</div>
              {detail.workshops.length === 0 ? (
                <p className="text-xs text-muted-foreground">未归属任何车间</p>
              ) : (
                <div className="flex flex-wrap gap-1">
                  {detail.workshops.map((ws) => (
                    <Badge key={ws.id} variant="outline">
                      {ws.name}
                    </Badge>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="mb-2 text-sm font-semibold">版本历史</div>
              <div className="space-y-1.5">
                {detail.versions.map((version) => (
                  <div
                    key={`${version.versionNo}-${version.createdAt}`}
                    className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-xs"
                  >
                    <span className="font-mono font-bold tabular-nums">
                      V{version.versionNo}
                    </span>
                    <span className="truncate text-muted-foreground">
                      {version.creatorName}
                    </span>
                    <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                      {dayjs(version.createdAt).format('MM-DD HH:mm')}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-sm font-semibold">
                关联实体（{detail.relatedEntities.length}）
              </div>
              {detail.relatedEntities.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无关联实体</p>
              ) : (
                <div className="space-y-1.5">
                  {detail.relatedEntities.map((ent) => (
                    <div
                      key={ent.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-xs"
                    >
                      <span className="truncate">{ent.name}</span>
                      <span className="shrink-0 font-mono text-muted-foreground">
                        {ent.code || '-'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
};

export default FileDetailSheet;
