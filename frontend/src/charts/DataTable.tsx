// A dense table of the rows behind a visualization. Used for the `table` chart type and
// for the "Data table" tab under every chart.

import type { Row, Visualization } from "../api/types";
import type { OpenCitations } from "./chartConfigs";

// Friendly column headings. The encoding already has titles for its channels ("Lead
// Sponsor", "Number of Trials"), so those are reused before falling back to a prettified key.
const KNOWN_LABELS: Record<string, string> = {
  share_pct: "Share (%)",
  contributing_trial_count: "Trials Behind This",
  nct_id: "NCT ID",
  bin: "Range",
  bin_start: "From",
  bin_end: "To",
  trial_count: "Number of Trials",
  country_iso3: "ISO3",
  source: "From",
  target: "To",
  weight: "Trials in Common",
  degree: "Connections",
  group_label: "Type",
};

function columnLabel(key: string, viz: Visualization): string {
  const enc = viz.encoding;
  for (const channel of [enc.x, enc.y, enc.series, enc.color, enc.size]) {
    if (channel?.field === key) return channel.title;
  }
  return KNOWN_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function DataTable({ viz, onOpenCitations }: { viz: Visualization; onOpenCitations: OpenCitations }) {
  // A network graph has no rows, so its edge list is shown instead
  const rows: Row[] =
    viz.type === "network_graph"
      ? ((viz.edges ?? []) as Row[]).map((e) => ({ source: e.source, target: e.target, weight: e.weight }))
      : ((viz.data ?? []) as Row[]);

  if (!rows.length) return <p className="text-xs text-slate-500">No rows.</p>;

  let columns = [...new Set(rows.flatMap(Object.keys))].filter((k) => k !== "citations");

  // When the measure already is a trial count, "trials behind this" is the same number twice.
  // Showing both looks like a bug, so the duplicate is hidden.
  const measureField = viz.encoding.y?.field;
  if (
    measureField &&
    columns.includes("contributing_trial_count") &&
    rows.every((r) => r.contributing_trial_count === r[measureField])
  ) {
    columns = columns.filter((c) => c !== "contributing_trial_count");
  }

  return (
    <div className="max-h-96 overflow-auto rounded-md border border-slate-200">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-slate-600">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-2 py-1 font-medium">
                {columnLabel(c, viz)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              className={`border-b border-slate-100 ${row.citations ? "cursor-pointer hover:bg-slate-50" : ""}`}
              onClick={
                row.citations
                  ? () => onOpenCitations(String(row[columns[0]]), row.citations, row.contributing_trial_count)
                  : undefined
              }
            >
              {columns.map((c) => {
                const value = row[c];
                const isNumber = typeof value === "number";
                return (
                  <td key={c} className={`px-2 py-1 ${isNumber ? "text-right tabular-nums" : ""}`}>
                    {value === null || value === undefined ? "—" : isNumber ? value.toLocaleString() : String(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
