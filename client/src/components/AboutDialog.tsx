import { useState } from 'react';
import { Info } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SidebarFooter } from '@/components/ui/sidebar';
import BrandLogo from '@/components/BrandLogo';

const AboutDialog = () => {
  const [open, setOpen] = useState(false);

  return (
    <SidebarFooter>
      <div className="px-2 pb-1 group-data-[collapsible=icon]:hidden">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          <Info className="size-3.5" />
          <span>关于繁工AI</span>
        </button>
        <p className="px-2 pt-1 text-[10px] text-sidebar-foreground/40">
          © 2026 胡繁荣
        </p>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <div className="flex items-center gap-3">
              <BrandLogo className="size-12 rounded-xl" />
              <div className="grid gap-1">
                <DialogTitle className="text-left">繁工AI</DialogTitle>
                <DialogDescription>复杂工程，AI 化简</DialogDescription>
              </div>
            </div>
          </DialogHeader>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>繁工AI · 开发者：胡繁荣</p>
            <p>版本：v3.3</p>
            <p className="text-xs leading-relaxed">
              安装为应用：在手机浏览器菜单选择「添加到主屏幕」，或在电脑
              Chrome / Edge 地址栏右侧点击安装图标，即可将繁工AI作为独立
              App 使用。
            </p>
            <p className="text-xs text-muted-foreground/60">© 2026 胡繁荣</p>
          </div>
        </DialogContent>
      </Dialog>
    </SidebarFooter>
  );
};

export default AboutDialog;
