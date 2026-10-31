// The single entry point for drawing a visualization. It looks at `viz.type` and picks the
// right component, so the pages never need to know how each chart type works.

import type { ResponseMeta, Visualization } from "../api/types";
import type { OpenCitations } from "./chartConfigs";
import { ChartJsChart } from "./ChartJsChart";
import { DataTable } from "./DataTable";
import { KpiCard } from "./KpiCard";
import { NetworkGraph } from "./NetworkGraph";

export function ChartRenderer({
  viz,
  meta,
  onOpenCitations,
}: {
  viz: Visualization;
  meta: ResponseMeta;
  onOpenCitations: OpenCitations;
}) {
  switch (viz.type) {
    case "network_graph":
      return <NetworkGraph viz={viz} onOpenCitations={onOpenCitations} />;
    case "kpi":
      return <KpiCard viz={viz} measureId={meta.measure?.id ?? "trial_count"} onOpenCitations={onOpenCitations} />;
    case "table":
      return <DataTable viz={viz} onOpenCitations={onOpenCitations} />;
    default:
      // bar_chart, grouped_bar_chart, stacked_bar_chart, time_series, histogram, scatter_plot, geo_map
      return <ChartJsChart viz={viz} onOpenCitations={onOpenCitations} />;
  }
}
