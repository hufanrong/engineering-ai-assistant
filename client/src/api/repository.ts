import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  RepositoryInfo,
  RotateKeyResponse,
} from '@shared/api.interface';

export async function getRepositoryInfo(
  projectId: string,
): Promise<RepositoryInfo> {
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/repository-info`,
  );
  return response.data;
}

export async function rotateApiKey(
  projectId: string,
): Promise<RotateKeyResponse> {
  const response = await axiosForBackend.post(
    `/api/projects/${projectId}/api-keys/rotate`,
  );
  return response.data;
}
