import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  ApprovalListResponse,
  ApproveApprovalResponse,
  RejectApprovalResponse,
} from '@shared/api.interface';

export interface ListApprovalsParams {
  status?: string;
  requestType?: string;
  offset?: number;
  limit?: number;
}

export async function listApprovals(
  projectId: string,
  params: ListApprovalsParams,
): Promise<ApprovalListResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set('status', params.status);
  if (params.requestType) search.set('requestType', params.requestType);
  if (params.offset !== undefined) search.set('offset', String(params.offset));
  if (params.limit !== undefined) search.set('limit', String(params.limit));
  const query = search.toString();
  const response = await axiosForBackend.get(
    `/api/projects/${projectId}/approvals${query ? `?${query}` : ''}`,
  );
  return response.data;
}

export async function approveApproval(id: string): Promise<ApproveApprovalResponse> {
  const response = await axiosForBackend.post(`/api/approvals/${id}/approve`);
  return response.data;
}

export async function rejectApproval(
  id: string,
  reason?: string,
): Promise<RejectApprovalResponse> {
  const response = await axiosForBackend.post(`/api/approvals/${id}/reject`, {
    reason,
  });
  return response.data;
}
