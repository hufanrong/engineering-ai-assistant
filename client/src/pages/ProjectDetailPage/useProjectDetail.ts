import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import {
  getProjectDetail,
  getProjectStatistics,
  listWorkshops,
} from '@client/src/api/project';
import type {
  ProjectDetailInfo,
  ProjectStatistics,
  WorkshopSummary,
} from '@shared/api.interface';

interface ProjectDetailData {
  detail: ProjectDetailInfo | null;
  statistics: ProjectStatistics | null;
  workshops: WorkshopSummary[];
  loading: boolean;
  error: string | null;
}

export function useProjectDetail(): ProjectDetailData & {
  reloadStatistics: () => Promise<void>;
  reloadWorkshops: () => Promise<void>;
} {
  const { id } = useParams<{ id: string }>();
  const [detail, setDetail] = useState<ProjectDetailInfo | null>(null);
  const [statistics, setStatistics] = useState<ProjectStatistics | null>(null);
  const [workshops, setWorkshops] = useState<WorkshopSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    if (!id) {
      return;
    }
    try {
      setError(null);
      const [detailData, statsData, workshopData] = await Promise.all([
        getProjectDetail(id),
        getProjectStatistics(id),
        listWorkshops(id),
      ]);
      setDetail(detailData);
      setStatistics(statsData);
      setWorkshops(workshopData.items);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载项目详情失败';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    void loadAll();
  }, [loadAll]);

  const reloadStatistics = useCallback(async () => {
    if (!id) {
      return;
    }
    const statsData = await getProjectStatistics(id);
    setStatistics(statsData);
  }, [id]);

  const reloadWorkshops = useCallback(async () => {
    if (!id) {
      return;
    }
    const workshopData = await listWorkshops(id);
    setWorkshops(workshopData.items);
  }, [id]);

  return {
    detail,
    statistics,
    workshops,
    loading,
    error,
    reloadStatistics,
    reloadWorkshops,
  };
}
