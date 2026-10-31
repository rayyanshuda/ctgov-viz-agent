// Draws any Chart.js-based visualization (bars, lines, scatter). The config comes from
// chartConfigs.ts; this component only hands it to react-chartjs-2.

import "chart.js/auto"; // registers every Chart.js chart type, scale and plugin
import { useMemo } from "react";
import { Chart } from "react-chartjs-2";
import type { Row, Visualization } from "../api/types";
import { buildChartSpec, type OpenCitations } from "./chartConfigs";
import { Legend } from "./Legend";

export function ChartJsChart({ viz, onOpenCitations }: { viz: Visualization; onOpenCitations: OpenCitations }) {
  // Memoised so the chart is only rebuilt when the data changes. Without this, any parent
  // re-render (like opening the drawer) would hand Chart.js a new config and replay the animation.
  const spec = useMemo(() => buildChartSpec(viz, onOpenCitations), [viz, onOpenCitations]);

  const canClick = ((viz.data ?? []) as Row[]).some((row) => row.citations?.length);
  const hint = [spec.hint, canClick ? "Click any mark to see its source trials." : ""].filter(Boolean).join(" ");

  return (
    <>
      {spec.legend && <Legend names={spec.legend} />}
      <div style={{ height: spec.height }}>
        <Chart type={spec.type} data={spec.data} options={spec.options} />
      </div>
      {hint && <p className="mt-2 text-xs text-slate-500">{hint}</p>}
    </>
  );
}
