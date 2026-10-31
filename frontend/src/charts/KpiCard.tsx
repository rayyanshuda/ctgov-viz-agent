// A "headline number" visualization: one big value, plus an optional breakdown table.

import type { Row, Visualization } from "../api/types";
import type { OpenCitations } from "./chartConfigs";

export function KpiCard({
  viz,
  measureId,
  onOpenCitations,
}: {
  viz: Visualization;
  measureId: string;
  onOpenCitations: OpenCitations;
}) {
  const rows = (viz.data ?? []) as Row[];
  if (!rows.length) return null;
  const [head, ...rest] = rows; // first row is the headline, the others are the breakdown

  return (
    <div>
      <div className="py-4">
        <div className="text-5xl font-semibold tabular-nums text-ink">{(head[measureId] ?? 0).toLocaleString()}</div>
        <div className="mt-1 text-sm text-slate-600">
          {head.label} ({head.unit})
        </div>
      </div>

      {rest.length > 0 && (
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
            <tr>
              <th className="px-2 py-1 font-medium">Breakdown</th>
              <th className="px-2 py-1 text-right font-medium">{head.unit}</th>
              <th className="px-2 py-1 text-right font-medium">Share</th>
            </tr>
          </thead>
          <tbody>
            {rest.map((r, i) => (
              <tr
                key={i}
                className="cursor-pointer border-b border-slate-100 hover:bg-slate-50"
                onClick={() => onOpenCitations(r.label, r.citations ?? [], r.contributing_trial_count)}
              >
                <td className="px-2 py-1">{r.label}</td>
                <td className="px-2 py-1 text-right tabular-nums">{(r[measureId] ?? 0).toLocaleString()}</td>
                <td className="px-2 py-1 text-right tabular-nums">{r.share_pct != null ? `${r.share_pct}%` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
