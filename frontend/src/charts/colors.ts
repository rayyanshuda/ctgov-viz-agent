// Chart colors. The first series is Intelligence Purple/indigo (DESIGN.md); the next ones
// are other distinct hues. Green, amber and red are left out on purpose: in this app they
// always mean status (success / warning / alert), never "series 4".
//
// These six passed the dataviz skill's validator (lightness, chroma, contrast and
// normal-vision separation). One neighbouring pair is close for colour-blind viewers, so
// every chart also has a legend and tooltips and never relies on colour alone.
export const SERIES = ["#6366f1", "#0891b2", "#db2777", "#ea580c", "#a855f7", "#0284c7"];

// With more than six groups the colours repeat; the legend and tooltips still name each one.
export const seriesColor = (i: number) => SERIES[i % SERIES.length];

// Lighter indigo for "ranked countries" bars, so they read as a different kind of chart
export const RANKED_BAR = "#818cf8";

// Neutrals used inside the canvas (Chart.js can't read Tailwind classes)
export const INK = "#0f172a";
export const TEXT_MUTED = "#64748b";
export const TEXT_SECONDARY = "#475569";
export const GRID = "#e2e8f0";
export const BASELINE = "#cbd5e1";
export const SURFACE = "#ffffff";
