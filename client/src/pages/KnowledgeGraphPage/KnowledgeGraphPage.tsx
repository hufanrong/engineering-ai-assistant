import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Network, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@client/src/components/ui/button';
import { Input } from '@client/src/components/ui/input';
import { Skeleton } from '@client/src/components/ui/skeleton';
import { getGraphData } from '@client/src/api/entity';
import type {
  GraphDataResponse,
  GraphEdge,
  GraphNode,
} from '@shared/api.interface';
import { ENTITY_TYPE } from '@shared/api.interface';
import GraphCanvas from './GraphCanvas';
import GraphFilterPanel from './GraphFilterPanel';
import NodeDetailDialog from './NodeDetailDialog';

const ALL_ENTITY_TYPES: string[] = Object.values(ENTITY_TYPE);

const KnowledgeGraphPage = () => {
  const { id: projectId } = useParams<{ id: string }>();

  const [graphData, setGraphData] = useState<GraphDataResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedTypes, setSelectedTypes] = useState<Set<string>>(
    new Set(ALL_ENTITY_TYPES),
  );
  const [keywordInput, setKeywordInput] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');
  const [highlightIds, setHighlightIds] = useState<Set<string> | null>(null);
  const [detailNode, setDetailNode] = useState<GraphNode | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const loadGraph = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await getGraphData(projectId);
      setGraphData(data);
    } catch {
      toast.error('加载图谱数据失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    const nodes: GraphNode[] = graphData?.nodes ?? [];
    for (const node of nodes) {
      counts[node.entityType] = (counts[node.entityType] ?? 0) + 1;
    }
    return counts;
  }, [graphData]);

  const allNodes: GraphNode[] = useMemo(
    () => graphData?.nodes ?? [],
    [graphData],
  );

  const filteredNodes = useMemo(
    () =>
      allNodes.filter((node: GraphNode) => selectedTypes.has(node.entityType)),
    [allNodes, selectedTypes],
  );

  const filteredEdges = useMemo(() => {
    const edges: GraphEdge[] = graphData?.edges ?? [];
    const visibleIds = new Set(
      filteredNodes.map((node: GraphNode) => node.id),
    );
    return edges.filter(
      (edge: GraphEdge) =>
        visibleIds.has(edge.source) && visibleIds.has(edge.target),
    );
  }, [graphData, filteredNodes]);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setDetailNode(node);
    setDialogOpen(true);
  }, []);

  const handleSearch = () => {
    const keyword = keywordInput.trim().toLowerCase();
    if (!keyword) {
      setAppliedKeyword('');
      setHighlightIds(null);
      return;
    }
    setAppliedKeyword(keywordInput.trim());
    const matched = new Set(
      allNodes
        .filter(
          (node: GraphNode) =>
            node.name.toLowerCase().includes(keyword) ||
            (node.code ?? '').toLowerCase().includes(keyword),
        )
        .map((node: GraphNode) => node.id),
    );
    if (matched.size === 0) {
      toast.warning('未找到匹配实体');
      setHighlightIds(null);
      return;
    }
    setHighlightIds(matched);
  };

  const clearSearch = () => {
    setKeywordInput('');
    setAppliedKeyword('');
    setHighlightIds(null);
  };

  const allCount = allNodes.length;

  const canvasBody = () => {
    if (loading) {
      return (
        <div className="absolute inset-0 p-4">
          <Skeleton className="h-full w-full" />
        </div>
      );
    }
    if (allCount === 0) {
      return (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
          <Network className="h-10 w-10 text-slate-500" />
          <p className="text-sm text-slate-400">
            暂无实体数据，请先在项目内上传台账文件或手动创建实体
          </p>
        </div>
      );
    }
    if (selectedTypes.size === 0) {
      return (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-slate-400">请至少选择一种实体类型</p>
        </div>
      );
    }
    if (filteredNodes.length === 0) {
      return (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-slate-400">当前筛选类型下暂无实体</p>
        </div>
      );
    }
    return (
      <GraphCanvas
        nodes={filteredNodes}
        edges={filteredEdges}
        highlightIds={highlightIds}
        onNodeClick={handleNodeClick}
      />
    );
  };

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">知识图谱</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            实体关系可视化 · 拖拽节点、滚轮缩放画布，点击节点查看详情
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-64">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="搜索实体名称或编号"
              value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSearch();
              }}
              className="pl-8"
            />
          </div>
          <Button
            size="sm"
            data-ai-section-type="button"
            onClick={handleSearch}
          >
            搜索
          </Button>
          {appliedKeyword && (
            <Button
              size="sm"
              variant="ghost"
              data-ai-section-type="button"
              onClick={clearSearch}
            >
              清除
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            data-ai-section-type="button"
            onClick={() => void loadGraph()}
            disabled={loading}
          >
            <RefreshCw />
            刷新
          </Button>
        </div>
      </div>

      <div className="flex min-h-[480px] flex-1 gap-4">
        <GraphFilterPanel
          selectedTypes={selectedTypes}
          typeCounts={typeCounts}
          onChange={setSelectedTypes}
        />

        <div className="relative flex-1 overflow-hidden rounded-md bg-[hsl(222_47%_15%)]">
          {!loading && filteredNodes.length > 0 && (
            <span className="absolute left-3 top-3 z-10 rounded-md bg-black/30 px-2 py-1 font-mono text-xs tabular-nums text-slate-300">
              {filteredNodes.length} 节点 / {filteredEdges.length} 关系
              {appliedKeyword ? ` / 匹配 ${highlightIds?.size ?? 0}` : ''}
            </span>
          )}
          {canvasBody()}
        </div>
      </div>

      <NodeDetailDialog
        open={dialogOpen}
        node={detailNode}
        projectId={projectId ?? ''}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
};

export default KnowledgeGraphPage;
