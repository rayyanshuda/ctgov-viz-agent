// Small display helpers shared by several pages.

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// +6, -3, or "unchanged", for comparing a chart before and after a refresh
export function formatDelta(before: number, after: number): string {
  const diff = after - before;
  if (diff === 0) return "unchanged";
  return `${diff > 0 ? "+" : "−"}${Math.abs(diff).toLocaleString()}`;
}
