// Shows a failed request: what went wrong, and (if the backend gave one) what to do about it.

import type { ApiError } from "../api/client";

export function ErrorBanner({ error }: { error: ApiError }) {
  return (
    <div role="alert" className="rounded-md border border-alert/40 bg-red-50/90 p-4">
      <h3 className="text-sm font-semibold capitalize text-red-800">{error.code.replace(/_/g, " ")}</h3>
      <p className="mt-1 text-sm text-slate-700">{error.message}</p>
      {error.remedy && <p className="mt-1 text-xs text-slate-500">{error.remedy}</p>}
    </div>
  );
}
