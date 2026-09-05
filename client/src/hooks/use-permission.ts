import { useAuth, ROLE_SUBJECT } from '@lark-apaas/client-toolkit/auth';

import { ROLE } from '@shared/api.interface';

export function useHasRole(requiredRoles: string[]): boolean {
  const { ability, isLoading } = useAuth();
  if (isLoading) return false;
  return requiredRoles.some((role: string) => ability.can(role, ROLE_SUBJECT));
}

export function useIsProjectManager(): boolean {
  return useHasRole([ROLE.SUPER_ADMIN, ROLE.ADMIN]);
}

export function useIsSuperAdmin(): boolean {
  return useHasRole([ROLE.SUPER_ADMIN]);
}
