// The trials behind one chart value, shown directly under the chart. Each excerpt is the
// exact text ClinicalTrials.gov returned, so every number can be checked against its source.

import { useEffect, useRef } from "react";
import type { Citation } from "../api/types";
import { buttonGhost, Card } from "./ui";

export interface SelectedSource {
  title: string;
  citations: Citation[];
  total?: number;
}

export function CitationsPanel({ source, onClose }: { source: SelectedSource | null; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  // The chart is tall, so the panel can open below the visible part of the page. Scroll it
  // into view, otherwise clicking a bar would look like it did nothing.
  useEffect(() => {
    if (source) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [source]);

  // Close with the Escape key
  useEffect(() => {
    if (!source) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [source, onClose]);

  if (!source) return null;
  const { title, citations, total } = source;

  return (
    <div ref={ref}>
      <Card
        title={`Sources: ${title}`}
        subtitle={
          citations.length
            ? `Showing ${citations.length} of ${(total ?? citations.length).toLocaleString()} contributing trials. Each excerpt is the exact value returned by the API.`
            : "No citations for this value."
        }
        actions={
          <button className={buttonGhost} onClick={onClose}>
            Close
          </button>
        }
      >
        {citations.length > 0 && (
          <ul className="grid gap-2 sm:grid-cols-2">
            {citations.map((c, i) => (
              // min-w-0 + break-*: long unbroken text (like the field path) must wrap instead of spilling out of the card
              <li key={`${c.nct_id}-${i}`} className="min-w-0 rounded-md border border-slate-200 p-2">
                <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-clinical hover:underline">
                  {c.nct_id}
                </a>
                <p className="mt-1 break-words rounded-md bg-slate-50 p-1 text-xs text-ink">{c.excerpt}</p>
                <p className="mt-1 break-words text-xs text-slate-600">{c.context}</p>
                <p className="mt-1 break-all font-mono text-xs text-slate-400">{c.field}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
