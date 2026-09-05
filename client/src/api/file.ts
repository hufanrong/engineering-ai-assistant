import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  CreateFileRequest,
  CreateFileResponse,
  DeleteViaApprovalResponse,
  FileDetail,
  FileListResponse,
  TaskListResponse,
  TaskRetryResponse,
} from '@shared/api.interface';

export interface FileListQuery {
  workshopId?: string;
  fileType?: string;
  parseStatus?: string;
  keyword?: string;
  offset?: number;
  limit?: number;
}

export interface TaskListQuery {
  status?: string;
  offset?: number;
  limit?: number;
}

export async function listFiles(
  projectId: string,
  query: FileListQuery = {},
): Promise<FileListResponse> {
  const params = new URLSearchParams();
  if (query.workshopId) params.set('workshopId', query.workshopId);
  if (query.fileType) params.set('fileType', query.fileType);
  if (query.parseStatus) params.set('parseStatus', query.parseStatus);
  if (query.keyword) params.set('keyword', query.keyword);
  if (query.offset !== undefined) params.set('offset', String(query.offset));
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  const qs = params.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/files${qs ? `?${qs}` : ''}`,
  );
  return response.data;
}

export async function createFile(
  projectId: string,
  data: CreateFileRequest,
): Promise<CreateFileResponse> {
  const response = await axiosForBackend.post(`/api/projects/${projectId}/files`, data);
  return response.data;
}

export async function getFileDetail(id: string): Promise<FileDetail> {
  const response = await axiosForBackend.get(`/api/files/${id}`);
  return response.data;
}

export async function listTasks(
  projectId: string,
  query: TaskListQuery = {},
): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  if (query.status) params.set('status', query.status);
  if (query.offset !== undefined) params.set('offset', String(query.offset));
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  const qs = params.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/tasks${qs ? `?${qs}` : ''}`,
  );
  return response.data;
}

export async function retryTask(id: string): Promise<TaskRetryResponse> {
  const response = await axiosForBackend.post(`/api/tasks/${id}/retry`);
  return response.data;
}

export async function deleteFile(id: string): Promise<DeleteViaApprovalResponse> {
  const response = await axiosForBackend.delete(`/api/files/${id}`);
  return response.data;
}
