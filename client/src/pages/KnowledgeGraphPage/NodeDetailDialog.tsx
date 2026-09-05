import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';

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
import type { GraphNode } from '@shared/api.interface';
import { ENTITY_TYPE_LABELS } from '@shared/api.interface';
import { ENTITY_COLOR } from './GraphCanvas';

interface NodeDetailDialogProps {
  open: boolean;
  node: GraphNode | null;
  projectId: string;
  onClose: () => void;
}

const NodeDetailDialog = ({
  open,
  node,
  projectId,
  onClose,
}: NodeDetailDialogProps) => {
  if (!node) return null;

  const typeColor = ENTITY_COLOR[node.entityType] ?? '#94a3b8';

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? onClose() : undefined)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{node.name}</DialogTitle>
          <DialogDescription>图谱实体节点详情</DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-[72px_1fr] items-center gap-y-3 text-sm">
          <span className="text-muted-foreground">编号</span>
          <span className="font-mono font-bold tabular-nums">
            {node.code ?? '-'}
          </span>

          <span className="text-muted-foreground">类型</span>
          <span>
            <Badge variant="outline" style={{ color: typeColor, borderColor: typeColor }}>
              {ENTITY_TYPE_LABELS[node.entityType] ?? node.entityType}
            </Badge>
          </span>

          <span className="text-muted-foreground">车间</span>
          <span>{node.workshopName ?? '-'}</span>

          <span className="text-muted-foreground">别名数</span>
          <span className="font-mono tabular-nums">{node.aliasCount}</span>
        </div>

        <p className="rounded-md bg-accent p-3 text-xs text-muted-foreground">
          属性、别名与归并状态等关键信息，请在实体管理页查看该实体的完整详情。
        </p>

        <DialogFooter>
          <Button asChild data-ai-section-type="button">
            <Link to={`/projects/${projectId}/entities`} onClick={onClose}>
              查看实体详情
              <ArrowRight />
            </Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default NodeDetailDialog;
