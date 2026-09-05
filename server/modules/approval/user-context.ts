import type { Request } from 'express';

export interface UserContextWithRoles {
  userId: string;
  roles?: string[];
}

export function isSuperAdmin(userContext: { roles?: string[] }): boolean {
  return userContext.roles?.includes('super_admin') ?? false;
}

export function extractUserContext(req: Request): UserContextWithRoles {
  const context = req.userContext as { userId?: string; roles?: string[] } | undefined;
  return { userId: context?.userId ?? '', roles: context?.roles };
}
