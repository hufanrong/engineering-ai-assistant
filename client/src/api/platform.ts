import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import './http';

import type {
  CreatePlatformMaterialRequest,
  CreatePlatformProcessRequest,
  CreatePlatformStandardRequest,
  PlatformListResponse,
  PlatformMaterialItem,
  PlatformProcessItem,
  PlatformStandardItem,
  UpdatePlatformMaterialRequest,
  UpdatePlatformProcessRequest,
  UpdatePlatformStandardRequest,
} from '@shared/api.interface';

export interface PlatformListParams {
  keyword?: string;
  offset?: number;
  limit?: number;
}

async function listPlatform<T>(
  resource: string,
  params: PlatformListParams,
): Promise<PlatformListResponse<T>> {
  const response = await axiosForBackend.get(`/api/platform/${resource}`, {
    params,
  });
  return response.data;
}

/* ==================== 规范库 ==================== */

export function listPlatformStandards(
  params: PlatformListParams,
): Promise<PlatformListResponse<PlatformStandardItem>> {
  return listPlatform<PlatformStandardItem>('standards', params);
}

export async function createPlatformStandard(
  body: CreatePlatformStandardRequest,
): Promise<void> {
  await axiosForBackend.post('/api/platform/standards', body);
}

export async function updatePlatformStandard(
  id: string,
  body: UpdatePlatformStandardRequest,
): Promise<void> {
  await axiosForBackend.put(`/api/platform/standards/${id}`, body);
}

export async function deletePlatformStandard(id: string): Promise<void> {
  await axiosForBackend.delete(`/api/platform/standards/${id}`);
}

/* ==================== 材料库 ==================== */

export function listPlatformMaterials(
  params: PlatformListParams,
): Promise<PlatformListResponse<PlatformMaterialItem>> {
  return listPlatform<PlatformMaterialItem>('materials', params);
}

export async function createPlatformMaterial(
  body: CreatePlatformMaterialRequest,
): Promise<void> {
  await axiosForBackend.post('/api/platform/materials', body);
}

export async function updatePlatformMaterial(
  id: string,
  body: UpdatePlatformMaterialRequest,
): Promise<void> {
  await axiosForBackend.put(`/api/platform/materials/${id}`, body);
}

export async function deletePlatformMaterial(id: string): Promise<void> {
  await axiosForBackend.delete(`/api/platform/materials/${id}`);
}

/* ==================== 工艺库 ==================== */

export function listPlatformProcesses(
  params: PlatformListParams,
): Promise<PlatformListResponse<PlatformProcessItem>> {
  return listPlatform<PlatformProcessItem>('processes', params);
}

export async function createPlatformProcess(
  body: CreatePlatformProcessRequest,
): Promise<void> {
  await axiosForBackend.post('/api/platform/processes', body);
}

export async function updatePlatformProcess(
  id: string,
  body: UpdatePlatformProcessRequest,
): Promise<void> {
  await axiosForBackend.put(`/api/platform/processes/${id}`, body);
}

export async function deletePlatformProcess(id: string): Promise<void> {
  await axiosForBackend.delete(`/api/platform/processes/${id}`);
}
