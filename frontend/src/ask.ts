// Plain helpers for the "ask a question" flow: the filter fields, turning them into a
// request, and the suggested questions. No React in here.

import type { VisualizeRequest } from "./api/types";

export const EXAMPLES = [
  "How has the number of trials for Keytruda changed per year since 2015?",
  "How are melanoma trials distributed across phases?",
  "Compare trial phases for pembrolizumab versus nivolumab",
  "Which countries have the most recruiting trials for type 2 diabetes?",
  "Show a network of sponsors and drugs for multiple myeloma trials",
  "Which drugs are most often studied together in breast cancer combination trials?",
  "How many trials is Pfizer running for lung cancer?",
];

// The optional filter fields. They are kept as strings because that is what inputs hold.
export interface Filters {
  drug_name: string;
  condition: string;
  sponsor: string;
  trial_phase: string;
  start_year: string;
  end_year: string;
}

export const EMPTY_FILTERS: Filters = {
  drug_name: "",
  condition: "",
  sponsor: "",
  trial_phase: "",
  start_year: "",
  end_year: "",
};

export function hasFilters(filters: Filters): boolean {
  return Object.values(filters).some((v) => v.trim() !== "");
}

// Turn the question and the filter fields into the JSON body the backend expects.
// Empty fields are left out so they don't act as filters.
export function buildRequest(query: string, filters: Filters): VisualizeRequest {
  const body: VisualizeRequest = { query: query.trim(), options: { citations_per_datum: 3 } };
  if (filters.drug_name.trim()) body.drug_name = filters.drug_name.trim();
  if (filters.condition.trim()) body.condition = filters.condition.trim();
  if (filters.sponsor.trim()) body.sponsor = filters.sponsor.trim();
  if (filters.trial_phase) body.trial_phase = [filters.trial_phase];
  if (filters.start_year) body.start_year = Number(filters.start_year);
  if (filters.end_year) body.end_year = Number(filters.end_year);
  return body;
}

// Describe the filtered trials in words, to use inside a suggested question.
function describeSubject(f: Filters): string {
  const parts = [f.drug_name ? `${f.drug_name} trials` : "trials"];
  if (f.condition) parts.push(`for ${f.condition}`);
  if (f.sponsor) parts.push(`sponsored by ${f.sponsor}`);
  return parts.join(" ");
}

// When someone sets filters but doesn't type a question, offer questions that are still
// interesting (no point asking for a phase breakdown if a phase is already chosen).
export function suggestedQuestions(f: Filters): string[] {
  const subject = describeSubject(f);
  const out = [
    `How many ${subject} are there, and what is their recruitment status?`,
    `How has the number of ${subject} changed per year?`,
    `Which countries have the most ${subject}?`,
  ];
  if (!f.trial_phase) out.push(`How are ${subject} distributed across phases?`);
  if (!f.sponsor) out.push(`Which sponsors run the most ${subject}?`);
  if (!f.drug_name) out.push(`Which drugs are most often studied in ${subject}?`);
  return out.slice(0, 4);
}

// Links like /?q=...&drug=...&phase=PHASE3 run a question on load, so a result can be
// bookmarked or scripted (the old demo page supported the same links).
export function filtersFromParams(p: URLSearchParams): Filters {
  return {
    drug_name: p.get("drug") ?? "",
    condition: p.get("condition") ?? "",
    sponsor: p.get("sponsor") ?? "",
    trial_phase: p.get("phase") ?? "",
    start_year: p.get("start_year") ?? "",
    end_year: p.get("end_year") ?? "",
  };
}
