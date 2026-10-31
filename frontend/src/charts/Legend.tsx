// A row of colour swatches + names. Drawn by us (not Chart.js) so it matches the page style.

import { seriesColor } from "./colors";

export function Legend({ names }: { names: string[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {names.map((name, i) => (
        <span key={name} className="inline-flex items-center gap-1">
          <i className="inline-block h-2 w-2 rounded-sm" style={{ background: seriesColor(i) }} />
          {name}
        </span>
      ))}
    </div>
  );
}
