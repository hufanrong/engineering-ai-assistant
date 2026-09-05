import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';
import type { AxiosError } from 'axios';
import { toast } from 'sonner';

export const NO_PERMISSION_MESSAGE = '无操作权限，请联系管理员分配角色';

function buildNoPermissionError(): Error {
  toast.error(NO_PERMISSION_MESSAGE);
  return new Error(NO_PERMISSION_MESSAGE);
}

axiosForBackend.interceptors.response.use(
  (response) => {
    if (response.status === 403) {
      return Promise.reject(buildNoPermissionError());
    }
    return response;
  },
  (error: AxiosError) => {
    if (error.response?.status === 403) {
      return Promise.reject(buildNoPermissionError());
    }
    return Promise.reject(error);
  },
);
