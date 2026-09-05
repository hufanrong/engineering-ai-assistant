import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  CreateProjectRequest,
  CreateProjectResponse,
  CreateWorkshopRequest,
  DashboardActivitiesResponse,
  DashboardSummary,
  DeleteProjectResponse,
  ProjectDetailInfo,
  ProjectListResponse,
  ProjectStatistics,
  UpdateProjectRequest,
  UpdateProjectResponse,
  WorkshopListResponse,
  WorkshopMutationResponse,
} from '@shared/api.interface';

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await axiosForBackend.get('/api/dashboard/summary');
  return response.data;
}

export async function getDashboardActivities(limit = 20): Promise<DashboardActivitiesResponse> {
  const response = await axiosForBackend.get(`/api/dashboard/activities?limit=${limit}`);
  return response.data;
}

export async function listProjects(
  keyword?: string,
  status?: string,
): Promise<ProjectListResponse> {
  const params = new URLSearchParams();
  if (keyword) params.set('keyword', keyword);
  if (status) params.set('status', status);
  const query = params.toString();
  const response = await axiosForBackend.get(`/api/projects${query ? `?${query}` : ''}`);
  return response.data;
}

export async function createProject(
  data: CreateProjectRequest,
): Promise<CreateProjectResponse> {
  const response = await axiosForBackend.post('/api/projects', data);
  return response.data;
}

export async function getProjectDetail(id: string): Promise<ProjectDetailInfo> {
  const response = await axiosForBackend.get(`/api/projects/${id}`);
  return response.data;
}

export async function updateProject(
  id: string,
  data: UpdateProjectRequest,
): Promise<UpdateProjectResponse> {
  const response = await axiosForBackend.put(`/api/projects/${id}`, data);
  return response.data;
}

export async function deleteProject(id: string): Promise<DeleteProjectResponse> {
  const response = await axiosForBackend.delete(`/api/projects/${id}`);
  return response.data;
}

export async function getProjectStatistics(id: string): Promise<ProjectStatistics> {
  const response = await axiosForBackend.get(`/api/projects/${id}/statistics`);
  return response.data;
}

export async function listWorkshops(projectId: string): Promise<WorkshopListResponse> {
  const response = await axiosForBackend.get(`/api/projects/${projectId}/workshops`);
  return response.data;
}

export async function createWorkshop(
  projectId: string,
  data: CreateWorkshopRequest,
): Promise<WorkshopMutationResponse> {
  const response = await axiosForBackend.post(`/api/projects/${projectId}/workshops`, data);
  return response.data;
}

export async function updateWorkshop(
  id: string,
  data: Partial<CreateWorkshopRequest>,
): Promise<WorkshopMutationResponse> {
  const response = await axiosForBackend.put(`/api/workshops/${id}`, data);
  return response.data;
}

export async function deleteWorkshop(id: string): Promise<WorkshopMutationResponse> {
  const response = await axiosForBackend.delete(`/api/workshops/${id}`);
  return response.data;
}
