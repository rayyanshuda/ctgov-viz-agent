// Everything shown for one answer: the chart, the agent's interpretation, any warnings,
// the "under the hood" tabs, and the source-trials drawer. Used by both the Ask page (a
// fresh answer) and the saved-chart page (a stored one), so they always look the same.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { VisualizeResponse } from "../api/types";
import { ChartRenderer } from "../charts/ChartRenderer";
import type { OpenCitations } from "../charts/chartConfigs";
import { CitationsPanel, type SelectedSource } from "./CitationsPanel";
import { MetaPanel } from "./MetaPanel";
import { ResultTabs } from "./ResultTabs";
import { Card } from "./ui";

export function ChartResult({ response, actions }: { response: VisualizeResponse; actions?: ReactNode }) {
  const { visualization: viz, meta } = response;
  const warnings = meta.warnings ?? [];
  const [source, setSource] = useState<SelectedSource | null>(null);

  // useCallback keeps this function the same between renders. The charts depend on it, and
  // a new function every render would make them redraw (and the network graph re-shuffle).
  const openCitations = useCallback<OpenCitations>(
    (title, citations, total) => setSource({ title, citations, total }),
    [],
  );
  const closeSource = useCallback(() => setSource(null), []);

  // A new answer arrived, so any open sources belong to the old one
  useEffect(() => setSource(null), [response]);

  return (
    <div className="flex flex-col gap-4">
      {actions}

      {warnings.length > 0 && (
        <div className="rounded-md border border-warning/50 bg-amber-50/90 p-4">
          <h3 className="text-sm font-semibold text-amber-800">Notes</h3>
          <ul className="mt-1 list-disc pl-4 text-sm text-slate-700">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-3">
        {/* The chart, and the sources of whatever value was clicked, directly under it */}
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-2">
          <Card title={viz?.title ?? "No matching trials"} subtitle={viz?.subtitle}>
            {viz ? (
              <ChartRenderer viz={viz} meta={meta} onOpenCitations={openCitations} />
            ) : (
              <p className="text-sm text-slate-600">
                The question was understood, but no trials matched. Nothing is drawn rather than inventing a chart.
              </p>
            )}
          </Card>
          <CitationsPanel source={source} onClose={closeSource} />
        </div>
        <MetaPanel meta={meta} />
      </div>

      <ResultTabs response={response} onOpenCitations={openCitations} />
    </div>
  );
}
