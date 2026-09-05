import { useCallback, useState, type ReactNode } from 'react';
import { Info } from 'lucide-react';

import { Badge } from '@client/src/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@client/src/components/ui/tabs';
import type { TableColumnsType } from '@lark-apaas/client-toolkit/antd-table';
import type {
  CreatePlatformMaterialRequest,
  CreatePlatformProcessRequest,
  CreatePlatformStandardRequest,
  PlatformMaterialItem,
  PlatformProcessItem,
  PlatformStandardItem,
} from '@shared/api.interface';
import {
  createPlatformMaterial,
  createPlatformProcess,
  createPlatformStandard,
  deletePlatformMaterial,
  deletePlatformProcess,
  deletePlatformStandard,
  listPlatformMaterials,
  listPlatformProcesses,
  listPlatformStandards,
  updatePlatformMaterial,
  updatePlatformProcess,
  updatePlatformStandard,
} from '@client/src/api/platform';
import PlatformLibPanel from './PlatformLibPanel';

type PlatformLibKey = 'standard' | 'material' | 'process';

const renderOptional = (value: string | undefined): string => value ?? '-';
const renderMono = (value: string | undefined): ReactNode =>
  value ? (
    <span className="font-mono font-medium tabular-nums">{value}</span>
  ) : (
    <span className="text-muted-foreground">-</span>
  );
const renderCategory = (value: string | undefined): ReactNode =>
  value ? <Badge variant="outline">{value}</Badge> : <span className="text-muted-foreground">-</span>;

/* ==================== 规范库配置 ==================== */

const standardColumns: TableColumnsType<PlatformStandardItem> = [
  {
    title: '标准号',
    dataIndex: 'standardCode',
    width: 160,
    ellipsis: true,
    render: (value: string) => renderMono(value),
  },
  {
    title: '名称',
    dataIndex: 'name',
    width: 260,
    ellipsis: true,
    render: (value: string) => <span className="font-medium">{value}</span>,
  },
  {
    title: '发布日期',
    dataIndex: 'publishDate',
    width: 120,
    render: (value: string | undefined) => (
      <span className="font-mono tabular-nums">{renderOptional(value)}</span>
    ),
  },
  {
    title: '分类',
    dataIndex: 'category',
    width: 140,
    ellipsis: true,
    render: (value: string | undefined) => renderCategory(value),
  },
];

const toStandardBody = (
  values: Record<string, string>,
): CreatePlatformStandardRequest => ({
  standardCode: values.standardCode,
  name: values.name,
  publishDate: values.publishDate || undefined,
  category: values.category || undefined,
  content: values.content || undefined,
});

/* ==================== 材料库配置 ==================== */

const materialColumns: TableColumnsType<PlatformMaterialItem> = [
  {
    title: '名称',
    dataIndex: 'name',
    width: 220,
    ellipsis: true,
    render: (value: string) => <span className="font-medium">{value}</span>,
  },
  {
    title: '材质',
    dataIndex: 'materialGrade',
    width: 120,
    ellipsis: true,
    render: (value: string | undefined) => renderOptional(value),
  },
  {
    title: '规格',
    dataIndex: 'spec',
    width: 160,
    ellipsis: true,
    render: (value: string | undefined) => renderOptional(value),
  },
  {
    title: '标准号',
    dataIndex: 'standardCode',
    width: 150,
    ellipsis: true,
    render: (value: string | undefined) => renderMono(value),
  },
  {
    title: '分类',
    dataIndex: 'category',
    width: 130,
    ellipsis: true,
    render: (value: string | undefined) => renderCategory(value),
  },
];

const toMaterialBody = (
  values: Record<string, string>,
): CreatePlatformMaterialRequest => ({
  name: values.name,
  materialGrade: values.materialGrade || undefined,
  spec: values.spec || undefined,
  standardCode: values.standardCode || undefined,
  category: values.category || undefined,
});

/* ==================== 工艺库配置 ==================== */

const processColumns: TableColumnsType<PlatformProcessItem> = [
  {
    title: '名称',
    dataIndex: 'name',
    width: 200,
    ellipsis: true,
    render: (value: string) => <span className="font-medium">{value}</span>,
  },
  {
    title: '适用范围',
    dataIndex: 'scope',
    width: 220,
    ellipsis: true,
    render: (value: string | undefined) => renderOptional(value),
  },
  {
    title: '说明',
    dataIndex: 'description',
    width: 260,
    ellipsis: true,
    render: (value: string | undefined) => renderOptional(value),
  },
  {
    title: '分类',
    dataIndex: 'category',
    width: 130,
    ellipsis: true,
    render: (value: string | undefined) => renderCategory(value),
  },
];

const toProcessBody = (
  values: Record<string, string>,
): CreatePlatformProcessRequest => ({
  name: values.name,
  scope: values.scope || undefined,
  description: values.description || undefined,
  category: values.category || undefined,
});

/* ==================== 页面 ==================== */

interface PlatformTotalBadgeProps {
  value: number;
}

const PlatformTotalBadge = ({ value }: PlatformTotalBadgeProps) => (
  <span className="ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full bg-muted px-1.5 py-0.5 font-mono text-xs tabular-nums text-muted-foreground">
    {value}
  </span>
);

const PlatformDataPage = () => {
  const [totals, setTotals] = useState<Record<PlatformLibKey, number>>({
    standard: 0,
    material: 0,
    process: 0,
  });

  const reportStandardTotal = useCallback((total: number) => {
    setTotals((prev: Record<PlatformLibKey, number>) => ({ ...prev, standard: total }));
  }, []);
  const reportMaterialTotal = useCallback((total: number) => {
    setTotals((prev: Record<PlatformLibKey, number>) => ({ ...prev, material: total }));
  }, []);
  const reportProcessTotal = useCallback((total: number) => {
    setTotals((prev: Record<PlatformLibKey, number>) => ({ ...prev, process: total }));
  }, []);

  return (
    <div className="space-y-4 p-4" data-ai-section-type="card-list">
      <div>
        <h1 className="text-xl font-semibold">平台级数据管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          规范库 / 材料库 / 工艺库的统一维护入口
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-md border border-primary/20 bg-primary/5 p-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <p className="text-sm text-foreground">
          平台级数据全局共享，所有项目检索时自动融合，不受车间过滤影响
        </p>
      </div>

      <Tabs defaultValue="standard" className="w-full">
        <TabsList>
          <TabsTrigger value="standard">
            规范库
            <PlatformTotalBadge value={totals.standard} />
          </TabsTrigger>
          <TabsTrigger value="material">
            材料库
            <PlatformTotalBadge value={totals.material} />
          </TabsTrigger>
          <TabsTrigger value="process">
            工艺库
            <PlatformTotalBadge value={totals.process} />
          </TabsTrigger>
        </TabsList>
        <TabsContent value="standard" className="mt-4">
          <PlatformLibPanel<PlatformStandardItem>
            libLabel="规范库"
            columns={standardColumns}
            fields={[
              { key: 'standardCode', label: '标准号', required: true, placeholder: '如 GB/T 50205' },
              { key: 'name', label: '名称', required: true, placeholder: '规范全称' },
              { key: 'publishDate', label: '发布日期', placeholder: '如 2020-01-01' },
              { key: 'category', label: '分类', placeholder: '如 验收类' },
              { key: 'content', label: '内容说明', multiline: true },
            ]}
            listApi={listPlatformStandards}
            createApi={(values) => createPlatformStandard(toStandardBody(values))}
            updateApi={(id, values) =>
              updatePlatformStandard(id, toStandardBody(values))
            }
            deleteApi={deletePlatformStandard}
            toFormValues={(item) => ({
              standardCode: item.standardCode,
              name: item.name,
              publishDate: item.publishDate ?? '',
              category: item.category ?? '',
              content: item.content ?? '',
            })}
            onTotalChange={reportStandardTotal}
          />
        </TabsContent>
        <TabsContent value="material" className="mt-4">
          <PlatformLibPanel<PlatformMaterialItem>
            libLabel="材料库"
            columns={materialColumns}
            fields={[
              { key: 'name', label: '名称', required: true, placeholder: '材料名称' },
              { key: 'materialGrade', label: '材质', placeholder: '如 Q355B' },
              { key: 'spec', label: '规格', placeholder: '如 Φ108×4' },
              { key: 'standardCode', label: '标准号', placeholder: '如 GB/T 8163' },
              { key: 'category', label: '分类', placeholder: '材料分类' },
            ]}
            listApi={listPlatformMaterials}
            createApi={(values) => createPlatformMaterial(toMaterialBody(values))}
            updateApi={(id, values) =>
              updatePlatformMaterial(id, toMaterialBody(values))
            }
            deleteApi={deletePlatformMaterial}
            toFormValues={(item) => ({
              name: item.name,
              materialGrade: item.materialGrade ?? '',
              spec: item.spec ?? '',
              standardCode: item.standardCode ?? '',
              category: item.category ?? '',
            })}
            onTotalChange={reportMaterialTotal}
          />
        </TabsContent>
        <TabsContent value="process" className="mt-4">
          <PlatformLibPanel<PlatformProcessItem>
            libLabel="工艺库"
            columns={processColumns}
            fields={[
              { key: 'name', label: '名称', required: true, placeholder: '工艺名称' },
              { key: 'scope', label: '适用范围', placeholder: '适用的工序或部位' },
              { key: 'category', label: '分类', placeholder: '工艺分类' },
              { key: 'description', label: '说明', multiline: true },
            ]}
            listApi={listPlatformProcesses}
            createApi={(values) => createPlatformProcess(toProcessBody(values))}
            updateApi={(id, values) =>
              updatePlatformProcess(id, toProcessBody(values))
            }
            deleteApi={deletePlatformProcess}
            toFormValues={(item) => ({
              name: item.name,
              scope: item.scope ?? '',
              description: item.description ?? '',
              category: item.category ?? '',
            })}
            onTotalChange={reportProcessTotal}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PlatformDataPage;
