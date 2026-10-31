// Short names for the types generated from the backend's OpenAPI file (schema.d.ts).
// Run `npm run gen:api` after changing a Pydantic model and TypeScript will point at
// every place in the UI that no longer matches.

import type { components } from "./schema";

type Schemas = components["schemas"];

export type VisualizeResponse = Schemas["VisualizeResponse"];
export type Visualization = Schemas["Visualization"];
export type ResponseMeta = Schemas["ResponseMeta"];
export type Capabilities = Schemas["CapabilitiesResponse"];
export type SavedChartSummary = Schemas["SavedChartSummary"];
export type SavedChartDetail = Schemas["SavedChartDetail"];
export type RefreshResponse = Schemas["RefreshResponse"];

// The JSON we send to POST /visualize. Written by hand because the generated request type
// marks every field that has a default as required, but the API lets us leave them out.
// Mirrors app/models/request.py (the backend also accepts a single value instead of a list).
export interface VisualizeRequest {
  query: string;
  drug_name?: string;
  condition?: string;
  sponsor?: string;
  trial_phase?: string[];
  start_year?: number;
  end_year?: number;
  options?: { citations_per_datum?: number };
}

// A pointer from one chart value back to a trial record. Mirrors `Citation` in
// app/models/response.py; it isn't in the generated file because it only appears inside
// the loosely typed chart rows.
export interface Citation {
  nct_id: string;
  field: string;
  excerpt: string;
  context: string;
  url: string;
}

// One row of chart data. The keys differ per chart (the response's `encoding` says which
// key holds x, y, series...), so a row is a loose object on purpose.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;
