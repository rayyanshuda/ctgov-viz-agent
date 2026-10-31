// Draws a network graph on a <canvas>: circles for entities, lines for shared trials.
// Hover a node to isolate its neighbours; click a node or a line to see its source trials.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Row, Visualization } from "../api/types";
import type { OpenCitations } from "./chartConfigs";
import { BASELINE, INK, SURFACE, SERIES } from "./colors";
import { Legend } from "./Legend";
import { layoutGraph, type GraphNode } from "./networkLayout";

const HEIGHT = 540;
const LABEL_COUNT = 14; // only the best-connected nodes get a permanent label; more is unreadable

export function NetworkGraph({ viz, onOpenCitations }: { viz: Visualization; onOpenCitations: OpenCitations }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);

  const rawNodes = (viz.nodes ?? []) as Row[];
  const rawEdges = (viz.edges ?? []) as Row[];

  // Legend names: each group's human label, in the same order as the colours
  const groupLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const n of rawNodes) labels[n.group] = n.group_label || n.group;
    return labels;
  }, [rawNodes]);
  const groupOrder = Object.keys(groupLabels);

  // Watch the container's width so the canvas is redrawn crisply when the window resizes
  useEffect(() => {
    const parent = canvasRef.current?.parentElement;
    if (!parent) return;
    const observer = new ResizeObserver(() => setWidth(Math.floor(parent.clientWidth)));
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !width) return;

    // Draw at the screen's pixel density so lines and text stay sharp
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = HEIGHT * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const { nodes, edges, byId, maxWeight } = layoutGraph(rawNodes, rawEdges, width, HEIGHT);
    const labelled = new Set([...nodes].sort((a, b) => b.degree - a.degree).slice(0, LABEL_COUNT).map((n) => n.id));
    let hover: GraphNode | undefined;

    const isNeighbour = (n: GraphNode) =>
      edges.some((e) => (e.source === hover!.id && e.target === n.id) || (e.target === hover!.id && e.source === n.id));

    function draw() {
      ctx.clearRect(0, 0, width, HEIGHT);

      // Lines first, so circles sit on top of them
      for (const e of edges) {
        const a = byId[e.source];
        const b = byId[e.target];
        const lit = hover && (e.source === hover.id || e.target === hover.id);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = lit ? SERIES[0] : BASELINE;
        ctx.globalAlpha = lit ? 0.85 : hover ? 0.12 : 0.38; // fade everything except the hovered node's links
        ctx.lineWidth = 0.6 + 3.4 * (e.weight / maxWeight);
        ctx.stroke();
      }

      for (const n of nodes) {
        const dim = hover && n !== hover && !isNeighbour(n);
        ctx.globalAlpha = dim ? 0.25 : 1;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, 6.2832);
        ctx.fillStyle = n.color;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = SURFACE; // white ring so overlapping circles stay distinct
        ctx.stroke();

        if (labelled.has(n.id) || n === hover) {
          ctx.globalAlpha = dim ? 0.3 : 1;
          ctx.font = "600 11px system-ui, sans-serif";
          ctx.textAlign = "center";
          const label = n.label.length > 20 ? n.label.slice(0, 18) + "…" : n.label;
          ctx.lineWidth = 3;
          ctx.strokeStyle = SURFACE; // white outline behind the text so lines don't cut through it
          ctx.strokeText(label, n.x, n.y - n.r - 5);
          ctx.fillStyle = INK;
          ctx.fillText(label, n.x, n.y - n.r - 5);
        }
      }
      ctx.globalAlpha = 1;
    }
    draw();

    // Mouse position relative to the canvas, and the node (if any) under it
    const mouse = (ev: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
    };
    const nodeAt = (x: number, y: number) => nodes.find((n) => (n.x - x) ** 2 + (n.y - y) ** 2 < (n.r + 5) ** 2);

    canvas.onmousemove = (ev) => {
      const { x, y } = mouse(ev);
      const found = nodeAt(x, y);
      if (found !== hover) {
        hover = found;
        draw();
        canvas.style.cursor = found ? "pointer" : "default";
      }
    };
    canvas.onmouseleave = () => {
      hover = undefined;
      draw();
    };
    canvas.onclick = (ev) => {
      const { x: mx, y: my } = mouse(ev);
      const node = nodeAt(mx, my);
      if (node) {
        onOpenCitations(`${node.label} — ${groupLabels[node.group]}`, (node.citations ?? []) as never, node.trial_count);
        return;
      }
      // Not on a node: was the click within 5px of a line?
      for (const e of edges) {
        const a = byId[e.source];
        const b = byId[e.target];
        // How far along the line (0 to 1) is the closest point to the click?
        const t = Math.max(
          0,
          Math.min(1, ((mx - a.x) * (b.x - a.x) + (my - a.y) * (b.y - a.y)) / ((b.x - a.x) ** 2 + (b.y - a.y) ** 2 || 1)),
        );
        const px = a.x + t * (b.x - a.x);
        const py = a.y + t * (b.y - a.y);
        if ((px - mx) ** 2 + (py - my) ** 2 < 25) {
          onOpenCitations(`${a.label} ↔ ${b.label}`, (e.citations ?? []) as never, e.weight);
          return;
        }
      }
    };

    return () => {
      canvas.onmousemove = canvas.onmouseleave = canvas.onclick = null;
    };
  }, [rawNodes, rawEdges, width, groupLabels, onOpenCitations]);

  return (
    <>
      {groupOrder.length > 1 && <Legend names={groupOrder.map((g) => groupLabels[g])} />}
      <div>
        <canvas ref={canvasRef} style={{ width: "100%", height: HEIGHT }} />
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {rawNodes.length} nodes, {rawEdges.length} edges. Node size is the number of connections; line thickness is the
        number of trials behind the link. Hover to isolate a node, click a node or line for its source trials.
      </p>
    </>
  );
}
