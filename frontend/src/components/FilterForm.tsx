// Optional filters that narrow WHICH trials are fetched. The question decides WHAT to show
// about them. Anything set here overrides what the agent would infer.
//
//   FilterFields - the six inputs in a grid (reused by the welcome view and InputPanel)
//   FilterForm   - FilterFields in its own card with a Visualize button (welcome view)

import type { ReactNode } from "react";
import { useCapabilities } from "../api/hooks";
import { useAsk } from "../AskContext";
import { EMPTY_FILTERS, hasFilters, type Filters } from "../ask";
import { buttonAi, buttonGhost, Card, inputClass, Spinner } from "./ui";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
      {label}
      {children}
    </label>
  );
}

export function ClearFiltersButton() {
  const { filters, setFilters } = useAsk();
  if (!hasFilters(filters)) return null;
  return (
    <button type="button" className={buttonGhost} onClick={() => setFilters(EMPTY_FILTERS)}>
      Clear
    </button>
  );
}

// `trailing` is an optional extra cell at the end of the grid, for buttons
export function FilterFields({ trailing }: { trailing?: ReactNode }) {
  const { filters, setFilters } = useAsk();
  const phases = useCapabilities().data?.filters.phases ?? [];

  // Update one field while keeping the rest
  const set = (key: keyof Filters) => (value: string) => setFilters({ ...filters, [key]: value });

  // The "@container" wrapper lets the columns (@xl, @3xl) depend on this box's width, not the screen's
  return (
    <div className="@container">
      <div className="grid grid-cols-2 gap-2 @xl:grid-cols-4 @3xl:grid-cols-7">
        <Field label="Drug">
          <input className={inputClass} placeholder="optional" value={filters.drug_name} onChange={(e) => set("drug_name")(e.target.value)} />
        </Field>
        <Field label="Condition">
          <input className={inputClass} placeholder="optional" value={filters.condition} onChange={(e) => set("condition")(e.target.value)} />
        </Field>
        <Field label="Sponsor">
          <input className={inputClass} placeholder="optional" value={filters.sponsor} onChange={(e) => set("sponsor")(e.target.value)} />
        </Field>
        <Field label="Phase">
          <select className={inputClass} value={filters.trial_phase} onChange={(e) => set("trial_phase")(e.target.value)}>
            <option value="">Any</option>
            {phases.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        <Field label="From year">
          <input className={inputClass} type="number" placeholder="optional" value={filters.start_year} onChange={(e) => set("start_year")(e.target.value)} />
        </Field>
        <Field label="To year">
          <input className={inputClass} type="number" placeholder="optional" value={filters.end_year} onChange={(e) => set("end_year")(e.target.value)} />
        </Field>
        {trailing && <div className="flex items-end gap-2">{trailing}</div>}
      </div>
    </div>
  );
}

export function FilterForm() {
  const { submit, isPending } = useAsk();

  return (
    <Card title="Filters" subtitle="Optional. They narrow which trials are retrieved.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <FilterFields
          trailing={
            <>
              <button type="submit" className={buttonAi} disabled={isPending}>
                {isPending ? <Spinner /> : null}
                Visualize
              </button>
              <ClearFiltersButton />
            </>
          }
        />
      </form>
    </Card>
  );
}
