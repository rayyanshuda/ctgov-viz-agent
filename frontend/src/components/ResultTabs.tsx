// The three "look under the hood" panels beneath a chart: the data table, the raw JSON
// response, and the exact ClinicalTrials.gov queries that produced the data.
// Only one is open at a time, and none is open by default.

import { useState } from "react";
import type { VisualizeResponse } from "../api/types";
import { DataTable } from "../charts/DataTable";
import type { OpenCitations } from "../charts/chartConfigs";
import { buttonGhost, Card } from "./ui";

type Tab = "table" | "json" | "requests";
const TABS: { id: Tab; label: string }[] = [
  { id: "table", label: "Data table" },
  { id: "json", label: "Raw JSON" },
  { id: "requests", label: "API queries used" },
];

export function ResultTabs({ response, onOpenCitations }: { response: VisualizeResponse; onOpenCitations: OpenCitations }) {
  const [open, setOpen] = useState<Tab | null>(null);
  const viz = response.visualization;
  const requests = response.meta.ctgov_requests ?? [];

  return (
    <Card>
      <div className="flex gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`${buttonGhost} ${open === tab.id ? "bg-slate-100" : ""}`}
            aria-expanded={open === tab.id}
            onClick={() => setOpen(open === tab.id ? null : tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {open === "table" && (
        <div className="mt-2">
          {viz ? <DataTable viz={viz} onOpenCitations={onOpenCitations} /> : <p className="text-xs text-slate-500">No data.</p>}
        </div>
      )}

      {open === "json" && (
        <pre className="mt-2 max-h-96 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-2 text-xs">
          {JSON.stringify(response, null, 2)}
        </pre>
      )}

      {open === "requests" && (
        <div className="mt-2">
          <p className="mb-2 text-xs text-slate-500">
            These are the exact queries sent to ClinicalTrials.gov. Open one to reproduce the underlying data by hand.
          </p>
          <ul className="flex flex-col gap-1">
            {requests.slice(0, 12).map((params, i) => {
              const url = "https://clinicaltrials.gov/api/v2/studies?" + new URLSearchParams(params).toString();
              return (
                <li key={i} className="break-all text-xs">
                  <a href={url} target="_blank" rel="noopener noreferrer" className="text-clinical hover:underline">
                    {url}
                  </a>
                </li>
              );
            })}
          </ul>
          {requests.length > 12 && <p className="mt-1 text-xs text-slate-500">…and {requests.length - 12} more.</p>}
        </div>
      )}
    </Card>
  );
}
