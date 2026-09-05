import React, { useEffect, useState } from 'react';
import { Route, Routes } from 'react-router-dom';

import Layout from './components/Layout';
import BrandSplash from './components/BrandSplash';
import NotFound from './pages/NotFound/NotFound';
import DashboardPage from './pages/DashboardPage/DashboardPage';
import ProjectListPage from './pages/ProjectListPage/ProjectListPage';
import ProjectDetailPage from './pages/ProjectDetailPage/ProjectDetailPage';
import RecordManagementPage from './pages/RecordManagementPage/RecordManagementPage';
import CapturePage from './pages/CapturePage/CapturePage';
import EntityManagementPage from './pages/EntityManagementPage/EntityManagementPage';
import PendingCenterPage from './pages/PendingCenterPage/PendingCenterPage';
import KnowledgeGraphPage from './pages/KnowledgeGraphPage/KnowledgeGraphPage';
import RepositoryInfoPage from './pages/RepositoryInfoPage/RepositoryInfoPage';
import PlatformDataPage from './pages/PlatformDataPage/PlatformDataPage';

const RoutesComponent = () => {
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => setShowSplash(false), 1600);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <>
      {showSplash && <BrandSplash />}
      <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="projects" element={<ProjectListPage />} />
        <Route path="projects/:id" element={<ProjectDetailPage />} />
        <Route path="projects/:id/entities" element={<EntityManagementPage />} />
        <Route path="projects/:id/pending" element={<PendingCenterPage />} />
        <Route path="projects/:id/graph" element={<KnowledgeGraphPage />} />
        <Route path="projects/:id/repository" element={<RepositoryInfoPage />} />
        <Route path="records" element={<RecordManagementPage />} />
        <Route path="capture" element={<CapturePage />} />
        <Route path="platform" element={<PlatformDataPage />} />
      </Route>
      <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
};

export default RoutesComponent;
