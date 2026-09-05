import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  CaptureResult,
  CaptureWithFileResponse,
  CreateRecordRequest,
  CreateRecordResponse,
  DeleteViaApprovalResponse,
  RecordDetail,
  RecordListResponse,
  RecordTypeConfigResponse,
  SupplementRequest,
  SupplementResponse,
  UpdateRecordRequest,
  UpdateRecordResponse,
} from '@shared/api.interface';

export interface ListRecordsParams {
  projectId?: string;
  recordType?: string;
  status?: string;
  keyword?: string;
  creator?: 'me';
  offset?: number;
  limit?: number;
}

export async function getRecordTypeConfigs(): Promise<RecordTypeConfigResponse> {
  const response = await axiosForBackend.get('/api/record-type-configs');
  return response.data;
}

export async function listSiteRecords(params: ListRecordsParams): Promise<RecordListResponse> {
  const search = new URLSearchParams();
  if (params.projectId) search.set('projectId', params.projectId);
  if (params.recordType) search.set('recordType', params.recordType);
  if (params.status) search.set('status', params.status);
  if (params.keyword) search.set('keyword', params.keyword);
  if (params.creator) search.set('creator', params.creator);
  if (params.offset !== undefined) search.set('offset', String(params.offset));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await axiosForBackend.get(`/api/site-records${query ? `?${query}` : ''}`);
  return response.data;
}

export async function getRecordDetail(id: string): Promise<RecordDetail> {
  const response = await axiosForBackend.get(`/api/site-records/${id}`);
  return response.data;
}

export async function updateRecord(
  id: string,
  data: UpdateRecordRequest,
): Promise<UpdateRecordResponse> {
  const response = await axiosForBackend.put(`/api/site-records/${id}`, data);
  return response.data;
}

export async function supplementRecord(
  id: string,
  data: SupplementRequest,
): Promise<SupplementResponse> {
  const response = await axiosForBackend.post(`/api/site-records/${id}/supplement`, data);
  return response.data;
}

export async function createRecord(data: CreateRecordRequest): Promise<CreateRecordResponse> {
  const response = await axiosForBackend.post('/api/site-records', data);
  return response.data;
}

export interface CaptureWithFileRequest {
  fileUrl: string;
  projectId: string;
  workshopId?: string;
  recordDate: string;
  source: string;
}

export async function captureWithFile(
  data: CaptureWithFileRequest,
): Promise<CaptureWithFileResponse> {
  const response = await axiosForBackend.post('/api/site-records/with-file', data);
  return response.data;
}

export async function getCaptureResult(taskId: string): Promise<CaptureResult> {
  const response = await axiosForBackend.get(`/api/site-records/capture-result/${taskId}`);
  return response.data;
}

export async function deleteSiteRecord(
  id: string,
): Promise<DeleteViaApprovalResponse> {
  const response = await axiosForBackend.delete(`/api/site-records/${id}`);
  return response.data;
}
