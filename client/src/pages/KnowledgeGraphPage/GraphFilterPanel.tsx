import { Button } from '@client/src/components/ui/button';
import { Checkbox } from '@client/src/components/ui/checkbox';

import { ENTITY_TYPE, ENTITY_TYPE_LABELS } from '@shared/api.interface';
import { ENTITY_COLOR } from './GraphCanvas';

const FILTER_TYPE_KEYS: string[] = Object.values(ENTITY_TYPE);

interface GraphFilterPanelProps {
  selectedTypes: Set<string>;
  typeCounts: Record<string, number>;
  onChange: (next: Set<string>) => void;
}

const GraphFilterPanel = ({
  selectedTypes,
  typeCounts,
  onChange,
}: GraphFilterPanelProps) => {
  const toggleType = (type: string, checked: boolean) => {
    const next = new Set(selectedTypes);
    if (checked) {
      next.add(type);
    } else {
      next.delete(type);
    }
    onChange(next);
  };

  const selectAll = () => onChange(new Set(FILTER_TYPE_KEYS));
  const clearAll = () => onChange(new Set<string>());

  return (
    <div className="flex w-60 shrink-0 flex-col rounded-md border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold">实体类型</span>
        <span className="text-xs text-muted-foreground">
          {selectedTypes.size}/{FILTER_TYPE_KEYS.length}
        </span>
      </div>

      <div className="mt-2 flex gap-2">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          data-ai-section-type="button"
          onClick={selectAll}
        >
          全选
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          data-ai-section-type="button"
          onClick={clearAll}
        >
          清空
        </Button>
      </div>

      <div className="mt-3 flex flex-col gap-3">
        {FILTER_TYPE_KEYS.map((type) => (
          <label
            key={type}
            htmlFor={`graph-filter-${type}`}
            className="flex cursor-pointer items-center gap-2.5 text-sm"
          >
            <Checkbox
              id={`graph-filter-${type}`}
              checked={selectedTypes.has(type)}
              onCheckedChange={(checked) => toggleType(type, checked === true)}
            />
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: ENTITY_COLOR[type] ?? '#94a3b8' }}
            />
            <span className="flex-1">{ENTITY_TYPE_LABELS[type] ?? type}</span>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {typeCounts[type] ?? 0}
            </span>
          </label>
        ))}
      </div>

      <p className="mt-auto pt-4 text-xs text-muted-foreground">
        取消勾选的类型节点将从画布中隐藏
      </p>
    </div>
  );
};

export default GraphFilterPanel;
