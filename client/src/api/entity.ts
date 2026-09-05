import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  AddAliasRequest,
  AddAliasResponse,
  BatchMergeDecisionRequest,
  BatchMergeDecisionResponse,
  ConflictListResponse,
  DeleteViaApprovalResponse,
  EntityDetail,
  EntityListResponse,
  GraphDataResponse,
  MergeDecisionRequest,
  MergeDecisionResponse,
  MergeQueueListResponse,
  PendingCounts,
  ResolveConflictRequest,
  ResolveConflictResponse,
} from '@shared/api.interface';

export interface ListEntitiesParams {
  entityType?: string;
  workshopId?: string;
  keyword?: string;
  mergeStatus?: string;
  offset?: number;
  limit?: number;
}

export interface ListMergeQueueParams {
  status?: string;
  offset?: number;
  limit?: number;
}

export interface ListConflictsParams {
  status?: string;
  offset?: number;
  limit?: number;
}

export async function listEntities(
  projectId: string,
  params: ListEntitiesParams,
): Promise<EntityListResponse> {
  const search = new URLSearchParams();
  if (params.entityType) search.set('entityType', params.entityType);
  if (params.workshopId) search.set('workshopId', params.workshopId);
  if (params.keyword) search.set('keyword', params.keyword);
  if (params.mergeStatus) search.set('mergeStatus', params.mergeStatus);
  if (params.offset !== undefined) search.set('offset', String(params.offset));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/entities${query ? `?${query}` : ''}`,
  );
  return response.data;
}

export async function getEntityDetail(id: string): Promise<EntityDetail> {
  const response = await axiosForBackend.get(`/api/entities/${id}`);
  return response.data;
}

export async function addEntityAlias(
  id: string,
  data: AddAliasRequest,
): Promise<AddAliasResponse> {
  const response = await axiosForBackend.post(`/api/entities/${id}/aliases`, data);
  return response.data;
}

export async function listMergeQueue(
  projectId: string,
  params: ListMergeQueueParams,
): Promise<MergeQueueListResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set('status', params.status);
  if (params.offset !== undefined) search.set('offset', String(params.offset));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/merge-queue${query ? `?${query}` : ''}`,
  );
  return response.data;
}

export async function decideMerge(
  id: string,
  data: MergeDecisionRequest,
): Promise<MergeDecisionResponse> {
  const response = await axiosForBackend.post(`/api/merge-queue/${id}/decision`, data);
  return response.data;
}

export async function batchDecideMerge(
  data: BatchMergeDecisionRequest,
): Promise<BatchMergeDecisionResponse> {
  const response = await axiosForBackend.post('/api/merge-queue/batch-decision', data);
  return response.data;
}

export async function listConflicts(
  projectId: string,
  params: ListConflictsParams,
): Promise<ConflictListResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set('status', params.status);
  if (params.offset !== undefined) search.set('offset', String(params.offset));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/conflicts${query ? `?${query}` : ''}`,
  );
  return response.data;
}

export async function resolveConflict(
  id: string,
  data: ResolveConflictRequest,
): Promise<ResolveConflictResponse> {
  const response = await axiosForBackend.post(`/api/conflicts/${id}/resolve`, data);
  return response.data;
}

export async function getPendingCounts(projectId: string): Promise<PendingCounts> {
  const response = await axiosForBackend.get(`/api/projects/${projectId}/pending-counts`);
  return response.data;
}

export async function deleteEntity(id: string): Promise<DeleteViaApprovalResponse> {
  const response = await axiosForBackend.delete(`/api/entities/${id}`);
  return response.data;
}

export async function getGraphData(
  projectId: string,
  entityTypes?: string[],
): Promise<GraphDataResponse> {
  const search = new URLSearchParams();
  if (entityTypes && entityTypes.length > 0) {
    search.set('entityTypes', entityTypes.join(','));
  }
  const query = search.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/graph${query ? `?${query}` : ''}`,
  );
  return response.data;
}
