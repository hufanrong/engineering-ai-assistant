import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { CallbackDataParams } from 'echarts/types/dist/shared';

import type { GraphEdge, GraphNode } from '@shared/api.interface';
import { RELATIONSHIP_TYPE_LABELS } from '@shared/api.interface';

export const ENTITY_COLOR: Record<string, string> = {
  equipment: '#3b82f6',
  pipe: '#22d3ee',
  valve: '#f472b6',
  instrument: '#eab308',
  material: '#22c55e',
  drawing: '#a855f7',
  document: '#94a3b8',
  record: '#f59e0b',
};

const DEFAULT_NODE_COLOR = '#94a3b8';
const EDGE_LINE_COLOR = '#475569';
const EDGE_LABEL_COLOR = '#64748b';
const NODE_LABEL_COLOR = '#cbd5e1';
const HIGHLIGHT_BORDER_COLOR = '#f59e0b';

interface GraphClickParams {
  dataType: string;
  dataIndex: number;
}

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightIds: Set<string> | null;
  onNodeClick: (node: GraphNode) => void;
}

function symbolSizeFor(aliasCount: number): number {
  const clamped = Math.min(Math.max(aliasCount, 0), 5);
  return 40 + clamped * 4;
}

const GraphCanvas = ({
  nodes,
  edges,
  highlightIds,
  onNodeClick,
}: GraphCanvasProps) => {
  const option: EChartsOption = useMemo(() => {
    const hasHighlight = highlightIds !== null && highlightIds.size > 0;

    const indexById = new Map<string, number>();
    nodes.forEach((node: GraphNode, index: number) => {
      indexById.set(node.id, index);
    });

    const nodeData = nodes.map((node: GraphNode) => {
      const color = ENTITY_COLOR[node.entityType] ?? DEFAULT_NODE_COLOR;
      const matched = hasHighlight && highlightIds.has(node.id);
      return {
        name: node.name,
        symbolSize: symbolSizeFor(node.aliasCount),
        itemStyle: {
          color,
          borderColor: hasHighlight
            ? matched
              ? HIGHLIGHT_BORDER_COLOR
              : color
            : '#ffffff',
          borderWidth: hasHighlight ? (matched ? 3 : 0) : 2,
          opacity: hasHighlight && !matched ? 0.15 : 1,
        },
      };
    });

    const linkData = edges
      .map(
        (edge: GraphEdge): {
          source: number;
          target: number;
          relLabel: string;
        } | null => {
          const source = indexById.get(edge.source);
          const target = indexById.get(edge.target);
          if (source === undefined || target === undefined) return null;
          return {
            source,
            target,
            relLabel:
              RELATIONSHIP_TYPE_LABELS[edge.relationshipType] ??
              edge.relationshipType,
          };
        },
      )
      .filter((link): link is { source: number; target: number; relLabel: string } => link !== null);

    return {
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          data: nodeData,
          links: linkData,
          label: {
            show: true,
            position: 'bottom',
            color: NODE_LABEL_COLOR,
            fontSize: 11,
          },
          edgeLabel: {
            show: true,
            fontSize: 10,
            color: EDGE_LABEL_COLOR,
            formatter: (p: CallbackDataParams) => {
              const data = p.data as { relLabel?: string } | undefined;
              return data?.relLabel ?? '';
            },
          },
          edgeSymbol: ['none', 'none'],
          lineStyle: {
            color: EDGE_LINE_COLOR,
            width: 1,
            opacity: 0.7,
            curveness: 0.1,
          },
          emphasis: {
            focus: 'adjacency',
            itemStyle: { borderWidth: 3 },
          },
          force: {
            repulsion: 220,
            edgeLength: 90,
            gravity: 0.12,
          },
        },
      ],
    };
  }, [nodes, edges, highlightIds]);

  const onEvents = useMemo(
    () => ({
      click: (params: GraphClickParams) => {
        if (params.dataType !== 'node') return;
        const node = nodes[params.dataIndex];
        if (node) onNodeClick(node);
      },
    }),
    [nodes, onNodeClick],
  );

  return (
    <ReactECharts
      option={option}
      theme="ud"
      onEvents={onEvents}
      className="h-full w-full"
      style={{ height: '100%', width: '100%' }}
    />
  );
};

export default GraphCanvas;
