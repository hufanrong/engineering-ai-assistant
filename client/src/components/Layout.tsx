import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  FolderKanban,
  NotebookPen,
  Smartphone,
  Database,
  LogOut,
  LogIn,
  Info,
} from 'lucide-react';
import { Outlet } from 'react-router-dom';
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
} from '@/components/ui/breadcrumb';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import BrandLogo from '@/components/BrandLogo';
import AboutDialog from '@/components/AboutDialog';
import { useCurrentUserProfile } from '@lark-apaas/client-toolkit/hooks/useCurrentUserProfile';
import { getDataloom } from '@lark-apaas/client-toolkit/dataloom';
import { logger } from '@lark-apaas/client-toolkit/logger';

const BRAND_NAME = '繁工AI';
const BRAND_TAGLINE = '复杂工程，AI 化简';

interface NavItem {
  path: string;
  title: string;
  icon: typeof LayoutDashboard;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', title: '仪表盘', icon: LayoutDashboard },
  { path: '/projects', title: '项目管理', icon: FolderKanban },
  { path: '/records', title: '现场记录', icon: NotebookPen },
  { path: '/capture', title: '移动采集', icon: Smartphone },
  { path: '/platform', title: '平台级数据', icon: Database },
];

const GUEST_AVATAR =
  'https://lf3-static.bytednsdoc.com/obj/eden-cn/LMfspH/ljhwZthlaukjlkulzlp/miao/no-person.svg';

function resolveTitle(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean);
  if (segments.length === 0) return '仪表盘';
  if (segments[0] === 'projects') {
    if (segments.length === 1) return '项目管理';
    if (segments[2] === 'entities') return '实体管理';
    if (segments[2] === 'pending') return '待确认中心';
    if (segments[2] === 'graph') return '知识图谱';
    if (segments[2] === 'repository') return '资料库连接信息';
    return '项目详情';
  }
  if (segments[0] === 'records') return '现场记录';
  if (segments[0] === 'capture') return '移动采集';
  if (segments[0] === 'platform') return '平台级数据';
  return BRAND_NAME;
}

function isActivePath(pathname: string, itemPath: string): boolean {
  if (itemPath === '/') return pathname === '/';
  return pathname === itemPath || pathname.startsWith(`${itemPath}/`);
}

const SidebarBrand = () => (
  <SidebarHeader>
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton size="lg" asChild>
          <Link to="/">
            <BrandLogo className="size-8 shrink-0 rounded-md" />
            <div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
              <span className="truncate font-semibold">{BRAND_NAME}</span>
              <span className="truncate text-xs text-sidebar-foreground/60">
                {BRAND_TAGLINE}
              </span>
            </div>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  </SidebarHeader>
);

const UserFooter = () => {
  const userInfo = useCurrentUserProfile();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isLoggedIn = Boolean(userInfo?.user_id);
  const displayName = isLoggedIn ? userInfo?.name || '已登录用户' : '游客';

  const handleLogout = async () => {
    setConfirmOpen(false);
    const dataloom = await getDataloom();
    const result = await dataloom.service.session.signOut();
    if (result.error) {
      logger.error('退出登录失败:', result.error.message);
      return;
    }
    window.location.reload();
  };

  const handleLogin = async () => {
    const dataloom = await getDataloom();
    dataloom.service.session.redirectToLogin();
  };

  return (
    <SidebarFooter>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton size="lg" asChild>
                <button type="button" className="w-full">
                  <Avatar className="size-8">
                    <AvatarImage
                      src={isLoggedIn ? userInfo?.avatar : GUEST_AVATAR}
                      alt={displayName}
                    />
                    <AvatarFallback>{displayName.slice(0, 1)}</AvatarFallback>
                  </Avatar>
                  <div className="grid flex-1 text-left text-sm leading-tight group-data-[collapsible=icon]:hidden">
                    <span className="truncate font-medium">{displayName}</span>
                  </div>
                </button>
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-48">
              <DropdownMenuLabel>{displayName}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {isLoggedIn ? (
                <DropdownMenuItem onClick={() => setConfirmOpen(true)}>
                  <LogOut className="size-4" />
                  退出登录
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onClick={handleLogin}>
                  <LogIn className="size-4" />
                  登录
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认退出登录？</AlertDialogTitle>
            <AlertDialogDescription>
              退出后将无法继续管理项目资料，重新登录后可恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleLogout}>退出</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarFooter>
  );
};

const LayoutContent = () => {
  const { pathname } = useLocation();
  const activeTitle = resolveTitle(pathname);

  return (
    <>
      <Sidebar collapsible="icon">
        <SidebarBrand />
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV_ITEMS.map((item) => (
                  <SidebarMenuItem key={item.path}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActivePath(pathname, item.path)}
                      tooltip={item.title}
                    >
                      <Link to={item.path}>
                        <item.icon className="size-4" />
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <UserFooter />
        <AboutDialog />
      </Sidebar>
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card px-4">
          <SidebarTrigger />
          <Breadcrumb className="self-center">
            <BreadcrumbList>
              <BreadcrumbItem className="text-foreground font-medium">
                {activeTitle}
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        </header>
        <div className="flex-1 overflow-auto p-4">
          <Outlet />
        </div>
      </main>
    </>
  );
};

const Layout = () => (
  <SidebarProvider>
    <LayoutContent />
  </SidebarProvider>
);

export default Layout;
