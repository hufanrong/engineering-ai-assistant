import { Loader2 } from 'lucide-react';

import { Button } from '@client/src/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@client/src/components/ui/dialog';

interface DeleteConfirmDialogProps {
  open: boolean;
  itemLabel: string;
  itemName?: string;
  isSuperAdmin: boolean;
  submitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const DeleteConfirmDialog = ({
  open,
  itemLabel,
  itemName,
  isSuperAdmin,
  submitting,
  onConfirm,
  onCancel,
}: DeleteConfirmDialogProps) => (
  <Dialog open={open} onOpenChange={(next) => (next ? undefined : onCancel())}>
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>删除{itemLabel}</DialogTitle>
        <DialogDescription>
          {isSuperAdmin
            ? `确认直接删除该${itemLabel}${itemName ? `「${itemName}」` : ''}吗？删除后不可恢复。`
            : `删除${itemLabel}${itemName ? `「${itemName}」` : ''}需超级管理员审批，确认提交？`}
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel} disabled={submitting}>
          取消
        </Button>
        <Button
          variant="destructive"
          data-ai-section-type="button"
          disabled={submitting}
          onClick={onConfirm}
        >
          {submitting && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
          {isSuperAdmin ? '确认删除' : '提交审批'}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);

export default DeleteConfirmDialog;
