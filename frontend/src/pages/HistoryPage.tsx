// The list of saved charts, newest first. Click a row to open it.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PAGE_SIZE, useCharts, useDeleteChart } from "../api/hooks";
import { Badge, Card, Spinner, buttonGhost, inputClass } from "../components/ui";
import { ErrorBanner } from "../components/ErrorBanner";
import { formatDate } from "../format";

export function HistoryPage() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const { data, error, isLoading } = useCharts(offset);
  const remove = useDeleteChart();

  // "No database configured" is not a failure of this page, so explain it instead of showing an alert
  if (error?.code === "configuration_error") {
    return (
      <Card title="Saved charts are switched off">
        <p className="text-sm text-slate-600">{error.message}</p>
        {error.remedy && <p className="mt-1 text-xs text-slate-500">{error.remedy}</p>}
      </Card>
    );
  }
  if (error) return <ErrorBanner error={error} />;

  const rows = (data ?? []).filter((c) => `${c.title} ${c.query} ${c.viz_type}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <Card
      title="Saved charts"
      subtitle="Every answer is saved as a snapshot you can reopen, share, or refresh."
      actions={
        <input
          className={`${inputClass} w-48`}
          placeholder="Filter this page…"
          aria-label="Filter saved charts"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      }
    >
      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-ai">
          <Spinner /> Loading…
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-slate-200">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-2 py-1 font-medium">Title</th>
                  <th className="px-2 py-1 font-medium">Question</th>
                  <th className="px-2 py-1 font-medium">Type</th>
                  <th className="px-2 py-1 text-right font-medium">Trials</th>
                  <th className="px-2 py-1 font-medium">Saved</th>
                  <th className="px-2 py-1" />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr
                    key={c.id}
                    className="cursor-pointer border-b border-slate-100 hover:bg-slate-50"
                    onClick={() => navigate(`/c/${c.id}`)}
                  >
                    <td className="px-2 py-1 font-medium text-clinical">
                      {c.title} {c.refreshed_from_id && <Badge tone="ai">Refresh</Badge>}
                    </td>
                    <td className="max-w-xs truncate px-2 py-1 text-slate-600">{c.query}</td>
                    <td className="px-2 py-1">{c.viz_type.replace(/_/g, " ")}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{c.total_matching.toLocaleString()}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-slate-500">{formatDate(c.created_at)}</td>
                    <td className="px-2 py-1 text-right">
                      <button
                        className="text-red-700 hover:underline"
                        onClick={(e) => {
                          e.stopPropagation(); // don't also open the chart
                          if (window.confirm("Delete this saved chart?")) remove.mutate(c.id);
                        }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-2 py-4 text-center text-slate-500">
                      {data?.length ? "No charts match the filter." : "Nothing saved yet. Ask a question to create one."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-2 flex items-center justify-end gap-2">
            <button className={buttonGhost} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </button>
            <button className={buttonGhost} disabled={(data?.length ?? 0) < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Next
            </button>
          </div>
        </>
      )}
    </Card>
  );
}
