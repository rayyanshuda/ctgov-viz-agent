// A saved chart at /c/<id>. It shows the stored snapshot exactly as it was generated, and
// can re-run the same analysis against live data. A refresh never changes this chart: it
// creates a new one that points back here.

import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useChart, useDeleteChart, useRefreshChart } from "../api/hooks";
import { Badge, Card, Spinner, buttonGhost, buttonPrimary } from "../components/ui";
import { ChartResult } from "../components/ChartResult";
import { CopyLinkButton } from "../components/CopyLinkButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { formatDate, formatDelta } from "../format";

// Passed along by navigate() right after a refresh, to show what changed
interface RefreshDelta {
  previousTotal: number;
  newTotal: number;
}

export function ChartPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const delta = (useLocation().state as { delta?: RefreshDelta } | null)?.delta;

  const { data: chart, error, isLoading } = useChart(id);
  const refresh = useRefreshChart();
  const remove = useDeleteChart();

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-sm text-ai">
          <Spinner /> Loading saved chart…
        </div>
      </Card>
    );
  }
  if (error || !chart) {
    return (
      <div className="flex flex-col gap-2">
        {error && <ErrorBanner error={error} />}
        <Link className="text-sm text-clinical hover:underline" to="/charts">
          ← Back to history
        </Link>
      </div>
    );
  }

  function onRefresh() {
    refresh.mutate(id, {
      onSuccess: (result) =>
        navigate(`/c/${result.chart.id}`, {
          state: { delta: { previousTotal: result.previous_total_matching, newTotal: result.new_total_matching } },
        }),
    });
  }

  function onDelete() {
    if (!window.confirm("Delete this saved chart? Its share link will stop working.")) return;
    remove.mutate(id, { onSuccess: () => navigate("/charts") });
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">{chart.query}</p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <Badge>Snapshot</Badge>
              Data as of {formatDate(chart.created_at)}
              {chart.refreshed_from_id && (
                <>
                  · Refreshed from{" "}
                  <Link className="text-clinical hover:underline" to={`/c/${chart.refreshed_from_id}`}>
                    previous version
                  </Link>
                </>
              )}
            </p>
            {delta && (
              <p className="mt-1 text-xs text-slate-700">
                Matching trials: {delta.previousTotal.toLocaleString()} → {delta.newTotal.toLocaleString()} (
                {formatDelta(delta.previousTotal, delta.newTotal)})
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button className={buttonPrimary} onClick={onRefresh} disabled={refresh.isPending}>
              {refresh.isPending ? "Refreshing…" : "Refresh with live data"}
            </button>
            <CopyLinkButton chartId={chart.id} />
            <button className={`${buttonGhost} text-red-700`} onClick={onDelete} disabled={remove.isPending}>
              Delete
            </button>
          </div>
        </div>
      </Card>

      {refresh.error && <ErrorBanner error={refresh.error} />}
      {remove.error && <ErrorBanner error={remove.error} />}

      <ChartResult response={chart.response} />
    </div>
  );
}
