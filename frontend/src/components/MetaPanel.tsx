// "How the agent understood the question": interpretation, assumptions, how much data was
// analysed, and which filters were applied. This is the AI layer, so it uses the AI purple.

import type { ResponseMeta } from "../api/types";
import { Badge, Card } from "./ui";

function coverageText(c: ResponseMeta["coverage"]): string {
  let text = `Analyzed ${c.analyzed.toLocaleString()} of ${c.total_matching.toLocaleString()} matching trials`;
  if (c.strategy === "exact_counts") text += " — bucket totals came directly from the API and are exact.";
  else text += c.truncated ? " (retrieval cap reached)." : " — complete.";
  if (c.records_missing_dimension) {
    text += ` ${c.records_missing_dimension.toLocaleString()} did not report the grouping field.`;
  }
  return text;
}

// A filter value can be a list, a plain value, or a nested object (when there are several
// cohorts, e.g. {Pembrolizumab: {interventions: [...]}}). Show each as readable text.
function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([k, v]) => `${k.replace(/_/g, " ")} ${formatValue(v)}`)
      .join("; ");
  }
  return String(value);
}

// Filters are objects like {conditions: ["melanoma"]}; show each as a small "key: value" tag
function FilterTags({ filters, tone }: { filters: Record<string, unknown>; tone: "ai" | "neutral" }) {
  const entries = Object.entries(filters);
  return (
    <>
      {entries.map(([key, value]) => (
        <Badge key={key} tone={tone}>
          {key.replace(/_/g, " ")}: {formatValue(value)}
        </Badge>
      ))}
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="mt-1 text-sm text-slate-700">{children}</div>
    </div>
  );
}

export function MetaPanel({ meta }: { meta: ResponseMeta }) {
  const c = meta.coverage;
  const coverageTone = c.strategy !== "exact_counts" && c.truncated ? "warning" : "success";
  const user = meta.filters_applied?.user ?? {};
  const inferred = meta.filters_applied?.inferred ?? {};

  return (
    <Card title="Agent interpretation" actions={<Badge tone="ai">AI</Badge>}>
      <div className="flex flex-col gap-4">
        <Section title="Interpretation">{meta.interpretation}</Section>
        <Section title="What one unit means">{meta.counting_semantics}</Section>
        <Section title="Assumptions">
          {meta.assumptions?.length ? (
            <ul className="list-disc pl-4">
              {meta.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          ) : (
            <span className="text-slate-500">None recorded.</span>
          )}
        </Section>
        <Section title="Coverage">
          <div className="mb-1">
            <Badge tone={coverageTone}>
              {c.strategy === "exact_counts" ? "Exact" : c.truncated ? "Capped" : "Complete"}
            </Badge>
          </div>
          {coverageText(c)}
        </Section>
        <Section title="Filters applied">
          {Object.keys(user).length + Object.keys(inferred).length === 0 ? (
            <span className="text-slate-500">None.</span>
          ) : (
            <>
              <div className="flex flex-wrap gap-1">
                <FilterTags filters={user} tone="neutral" />
                <FilterTags filters={inferred} tone="ai" />
              </div>
              <p className="mt-1 text-xs text-slate-500">Grey: from your inputs. Purple: inferred by the agent.</p>
            </>
          )}
        </Section>
      </div>
    </Card>
  );
}
