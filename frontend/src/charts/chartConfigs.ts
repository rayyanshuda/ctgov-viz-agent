// Turns a visualization from the API into a Chart.js configuration.
// One function per chart family. They are plain functions (data in, config out) so each
// can be read on its own. The response's `encoding` says which row key is x, y, series...
// so nothing here hard-codes a field name.

import type { Citation, Row, Visualization } from "../api/types";
import { BASELINE, GRID, INK, RANKED_BAR, SURFACE, TEXT_MUTED, TEXT_SECONDARY, seriesColor } from "./colors";

// Called when someone clicks a mark: opens the "source trials" drawer
export type OpenCitations = (title: string, citations: Citation[], total?: number) => void;

export interface ChartSpec {
  type: "bar" | "line" | "scatter";
  // Chart.js config objects are deeply nested and differ per type; typing them fully would add
  // a lot of noise for no safety, so they are left loose.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  options: any;
  legend?: string[]; // series names, shown as a legend when there are two or more
  hint?: string; // small helper text under the chart
  height: number; // pixels
}

// Skip animation for people who prefer reduced motion, and for ?static=1 (used when taking
// screenshots, because a half-finished animation looks like a blank chart).
const STATIC_RENDER =
  new URLSearchParams(location.search).get("static") === "1" ||
  matchMedia("(prefers-reduced-motion: reduce)").matches;

// Settings shared by every Chart.js chart: tooltip style, axes, grid, fonts.
function baseOptions(
  xTitle: string | undefined,
  yTitle: string | undefined,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onClick: (event: any, elements: any[]) => void,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): any {
  const tickFont = { size: 11 };
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: STATIC_RENDER ? false : { duration: 320 },
    onClick,
    plugins: {
      legend: { display: false }, // we draw our own legend (Legend.tsx)
      tooltip: {
        backgroundColor: SURFACE,
        titleColor: INK,
        bodyColor: TEXT_SECONDARY,
        borderColor: GRID,
        borderWidth: 1,
        padding: 8,
        boxPadding: 4,
        cornerRadius: 6,
      },
    },
    scales: {
      x: {
        title: { display: !!xTitle, text: xTitle, color: TEXT_MUTED, font: tickFont },
        grid: { display: false },
        border: { color: BASELINE },
        ticks: { color: TEXT_MUTED, font: tickFont, maxRotation: 45 },
      },
      y: {
        beginAtZero: true,
        title: { display: !!yTitle, text: yTitle, color: TEXT_MUTED, font: tickFont },
        grid: { color: GRID, drawTicks: false },
        border: { display: false },
        ticks: { color: TEXT_MUTED, font: tickFont, precision: 0 },
      },
    },
  };
}

// Read the row key names out of the encoding. x and y are always present on chart types.
function fields(viz: Visualization) {
  const enc = viz.encoding;
  return {
    enc,
    rows: (viz.data ?? []) as Row[],
    xField: enc.x?.field ?? "",
    yField: enc.y?.field ?? "",
    seriesField: enc.series?.field ?? null,
  };
}

// Click on a single-series mark -> open the trials behind that row
function openFromChart(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  elements: any[],
  rows: Row[],
  viz: Visualization,
  open: OpenCitations,
) {
  if (!elements.length) return;
  const row = rows[elements[0].index];
  if (!row) return;
  const label = row[viz.encoding.x?.field ?? ""] ?? row.label ?? row.nct_id;
  open(String(label), row.citations ?? [], row.contributing_trial_count);
}

// ---- Scatter: one dot per trial, optionally coloured by a group -------------------------
export function scatterConfig(viz: Visualization, open: OpenCitations): ChartSpec {
  const { enc, rows, xField, yField } = fields(viz);
  const colorField = enc.color?.field ?? null;
  const groups = colorField ? [...new Set(rows.map((r) => r[colorField]))] : ["All trials"];

  const options = baseOptions(enc.x?.title, enc.y?.title, (_e, els) => openFromChart(els, rows, viz, open));
  options.scales.x.beginAtZero = false;
  options.scales.y.beginAtZero = false;
  options.scales.x.type = "linear";
  options.plugins.tooltip.callbacks = {
    title: (items: { raw: { row: Row } }[]) => items[0].raw.row.label || items[0].raw.row.nct_id,
    label: (item: { parsed: { x: number; y: number } }) =>
      `${enc.x?.title}: ${item.parsed.x} · ${enc.y?.title}: ${item.parsed.y}`,
  };

  return {
    type: "scatter",
    height: 420,
    data: {
      datasets: groups.map((g, i) => ({
        label: String(g),
        data: rows
          .filter((r) => !colorField || r[colorField] === g)
          .map((r) => ({ x: r[xField], y: r[yField], row: r })),
        backgroundColor: seriesColor(i) + "cc", // "cc" = slightly transparent so overlaps show
        borderColor: SURFACE,
        borderWidth: 2,
        pointRadius: 5,
        pointHoverRadius: 8,
      })),
    },
    options,
    legend: groups.length > 1 ? groups.map(String) : undefined,
  };
}

// ---- Grouped / stacked bars: one bar per (category, series) pair --------------------------
export function groupedBarConfig(viz: Visualization, open: OpenCitations): ChartSpec {
  const { enc, rows, xField, yField, seriesField } = fields(viz);
  const categories = [...new Set(rows.map((r) => r[xField]))];
  const seriesNames = [...new Set(rows.map((r) => r[seriesField!]))];

  // Clicking a bar -> find the row for that category + series
  const onClick = (_e: unknown, els: { index: number; datasetIndex: number }[]) => {
    if (!els.length) return;
    const category = categories[els[0].index];
    const series = seriesNames[els[0].datasetIndex];
    const row = rows.find((r) => r[xField] === category && r[seriesField!] === series);
    if (row) open(`${category} — ${series}`, row.citations ?? [], row.contributing_trial_count);
  };

  const options = baseOptions(enc.x?.title, enc.y?.title, onClick);
  if (viz.type === "stacked_bar_chart") {
    options.scales.x.stacked = true;
    options.scales.y.stacked = true;
  }

  return {
    type: "bar",
    height: 420,
    data: {
      labels: categories,
      datasets: seriesNames.map((name, i) => ({
        label: String(name),
        data: categories.map((c) => {
          const hit = rows.find((r) => r[xField] === c && r[seriesField!] === name);
          return hit ? hit[yField] : 0;
        }),
        backgroundColor: seriesColor(i),
        borderRadius: { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
        borderSkipped: false,
        borderColor: SURFACE, // thin gap so neighbouring bars don't merge
        borderWidth: { top: 0, left: 1, right: 1, bottom: 0 },
      })),
    },
    options,
    legend: seriesNames.map(String),
  };
}

// ---- Line: one point per period (time series) -----------------------------------------
export function lineConfig(viz: Visualization, open: OpenCitations): ChartSpec {
  const { enc, rows, xField, yField } = fields(viz);
  const color = seriesColor(0);
  const options = baseOptions(enc.x?.title, enc.y?.title, (_e, els) => openFromChart(els, rows, viz, open));
  options.interaction = { mode: "index", intersect: false };

  return {
    type: "line",
    height: 420,
    data: {
      labels: rows.map((r) => r[xField]),
      datasets: [
        {
          label: enc.y?.title,
          data: rows.map((r) => r[yField]),
          borderColor: color,
          backgroundColor: color + "1f", // very light fill under the line
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 8,
          tension: 0.25,
          fill: true,
          pointBackgroundColor: color,
          pointBorderColor: SURFACE,
          pointBorderWidth: 2,
        },
      ],
    },
    options,
  };
}

// ---- Simple bars: bar_chart, histogram and geo_map -------------------------------------
export function barConfig(viz: Visualization, open: OpenCitations): ChartSpec {
  const { enc, rows, xField, yField } = fields(viz);
  const isHistogram = viz.type === "histogram";
  const isGeo = viz.type === "geo_map";

  // Long category lists read better as horizontal bars. A histogram is always vertical,
  // because turning a distribution on its side makes its shape harder to see.
  const horizontal = isGeo || (!isHistogram && rows.length > 14);

  // Horizontal bars need ~26px per row so every label fits; other charts use a fixed height.
  const needsTallPlot = isGeo || (!isHistogram && rows.length > 14);
  const height = needsTallPlot ? Math.max(420, Math.min(rows.length * 26 + 70, 1100)) : 420;

  const options = baseOptions(enc.x?.title, enc.y?.title, (_e, els) => openFromChart(els, rows, viz, open));
  if (horizontal) {
    options.indexAxis = "y";
    // Swap the axis settings so the labels end up on the vertical axis
    [options.scales.x, options.scales.y] = [options.scales.y, options.scales.x];
    options.scales.y.grid = { display: false };
    options.scales.x.grid = { color: GRID, drawTicks: false };
    // Show every label. Chart.js would otherwise skip some when they don't fit.
    options.scales.y.ticks.autoSkip = false;
    options.scales.y.ticks.maxRotation = 0;
  }
  if (isGeo) {
    options.plugins.tooltip.callbacks = {
      afterLabel: (item: { dataIndex: number }) => {
        const iso = rows[item.dataIndex].country_iso3;
        return iso ? `ISO3: ${iso}` : "No ISO3 code (dissolved state)";
      },
    };
  }

  return {
    type: "bar",
    height,
    data: {
      labels: rows.map((r) => r[xField]),
      datasets: [
        {
          label: enc.y?.title,
          data: rows.map((r) => r[yField]),
          backgroundColor: isGeo ? RANKED_BAR : seriesColor(0),
          borderRadius: horizontal
            ? { topRight: 4, bottomRight: 4, topLeft: 0, bottomLeft: 0 }
            : { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 },
          borderSkipped: false,
          categoryPercentage: isHistogram ? 1.0 : 0.82,
          barPercentage: isHistogram ? 0.98 : 0.9,
        },
      ],
    },
    options,
    hint: isGeo
      ? "Shown as ranked bars. The response also carries an ISO3 code per row (encoding.location), so the same payload can drive a map."
      : undefined,
  };
}

// Pick the right builder for a chart type. network_graph, kpi and table are not Chart.js
// charts and are handled by their own components (see ChartRenderer.tsx).
export function buildChartSpec(viz: Visualization, open: OpenCitations): ChartSpec {
  if (viz.type === "scatter_plot") return scatterConfig(viz, open);
  if (viz.encoding.series) return groupedBarConfig(viz, open);
  if (viz.type === "time_series") return lineConfig(viz, open);
  return barConfig(viz, open);
}
