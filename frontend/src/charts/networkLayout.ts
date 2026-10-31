// Works out where each node of a network graph sits on the canvas.
//
// It is a small "force-directed" simulation: every node pushes every other node away, every
// edge pulls its two ends together (heavier edges pull harder), and a weak force pulls
// everything toward the middle. After 450 steps the picture settles into a readable layout.
// No library needed, and it is a straight port of the original demo page.

import type { Row } from "../api/types";
import { seriesColor } from "./colors";

export interface GraphNode {
  id: string;
  label: string;
  group: string;
  degree: number; // how many links the node has; drawn as its size
  trial_count?: number;
  citations?: Row[];
  x: number;
  y: number;
  vx: number; // current speed, used only while the layout runs
  vy: number;
  r: number; // circle radius
  color: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  weight: number; // number of trials supporting the link; drawn as line thickness
  citations?: Row[];
}

export function layoutGraph(rawNodes: Row[], rawEdges: Row[], W: number, H: number) {
  const groups = [...new Set(rawNodes.map((n) => n.group as string))];
  const maxDegree = Math.max(1, ...rawNodes.map((n) => n.degree));
  const maxWeight = Math.max(1, ...rawEdges.map((e) => e.weight));

  // Start the nodes on a circle (with a little jitter) so the simulation has something to untangle
  const nodes: GraphNode[] = rawNodes.map((n, i) => {
    const angle = (i / rawNodes.length) * 6.283;
    const radius = Math.min(W, H) * 0.32;
    return {
      ...(n as GraphNode),
      x: W / 2 + Math.cos(angle) * radius + (Math.random() - 0.5) * 20,
      y: H / 2 + Math.sin(angle) * radius + (Math.random() - 0.5) * 20,
      vx: 0,
      vy: 0,
      r: 5 + 11 * Math.sqrt(n.degree / maxDegree),
      color: seriesColor(groups.indexOf(n.group)),
    };
  });
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  // Ignore edges that point at a node that isn't in the list
  const edges = (rawEdges as GraphEdge[]).filter((e) => byId[e.source] && byId[e.target]);

  for (let step = 0; step < 450; step++) {
    // 1. Every pair of nodes pushes apart
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const d2 = dx * dx + dy * dy || 0.01;
        const d = Math.sqrt(d2);
        const force = 5200 / d2;
        a.vx -= (dx / d) * force;
        a.vy -= (dy / d) * force;
        b.vx += (dx / d) * force;
        b.vy += (dy / d) * force;
      }
    }
    // 2. Each edge pulls its two nodes toward a resting length of 115px
    for (const e of edges) {
      const a = byId[e.source];
      const b = byId[e.target];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (d - 115) * 0.011 * (0.4 + 0.6 * (e.weight / maxWeight));
      a.vx += (dx / d) * force;
      a.vy += (dy / d) * force;
      b.vx -= (dx / d) * force;
      b.vy -= (dy / d) * force;
    }
    // 3. Move the nodes: a gentle pull to the centre, some friction, and stay inside the canvas
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.006;
      n.vy += (H / 2 - n.y) * 0.006;
      n.vx *= 0.82;
      n.vy *= 0.82;
      n.x = Math.max(n.r + 4, Math.min(W - n.r - 4, n.x + n.vx));
      n.y = Math.max(n.r + 4, Math.min(H - n.r - 4, n.y + n.vy));
    }
  }

  return { nodes, edges, byId, maxWeight, groups };
}
