import type { CallGraph, GraphEdge, GraphNode } from "@plural/client";

export interface PlacedNode extends GraphNode {
  x: number;
  y: number;
  layer: number;
}

export interface PlacedEdge extends GraphEdge {
  /** An SVG path from the caller's right side to the called node's left side. */
  path: string;
  /** The stroke in pixels: thicker for more tokens. */
  width: number;
}

export interface GraphLayout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
}

export const NODE = { width: 184, height: 58, gapX: 104, gapY: 14, pad: 16 };

const KIND_ORDER = { person: 0, agent: 1, model: 2, tool: 3 } as const;

/**
 * Lay a call graph out left to right: callers in one column, what they call in the next. A node
 * sits one column past its furthest caller, so every edge points right.
 */
export function layoutGraph(graph: CallGraph): GraphLayout {
  const layer = new Map<string, number>(graph.nodes.map((node) => [node.id, 0]));
  // Longest path by relaxing the edges; the bound stops a cycle a broken trace might hold.
  for (let pass = 0; pass < graph.nodes.length; pass += 1) {
    let moved = false;
    for (const edge of graph.edges) {
      const next = (layer.get(edge.from) ?? 0) + 1;
      if (next > (layer.get(edge.to) ?? 0)) {
        layer.set(edge.to, next);
        moved = true;
      }
    }
    if (!moved) break;
  }
  const columns = new Map<number, GraphNode[]>();
  for (const node of graph.nodes) {
    const at = layer.get(node.id) ?? 0;
    columns.set(at, [...(columns.get(at) ?? []), node]);
  }
  const tallest = Math.max(0, ...[...columns.values()].map((column) => column.length));
  const height = NODE.pad * 2 + tallest * NODE.height + Math.max(0, tallest - 1) * NODE.gapY;
  const placed = new Map<string, PlacedNode>();
  for (const [at, column] of columns) {
    const sorted = column.slice().sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || b.tokens - a.tokens || b.calls - a.calls);
    const used = sorted.length * NODE.height + (sorted.length - 1) * NODE.gapY;
    sorted.forEach((node, index) => {
      placed.set(node.id, {
        ...node,
        layer: at,
        x: NODE.pad + at * (NODE.width + NODE.gapX),
        // A short column is centred beside the tallest one.
        y: (height - used) / 2 + index * (NODE.height + NODE.gapY),
      });
    });
  }
  const most = Math.max(1, ...graph.edges.map((edge) => edge.tokens));
  const edges = graph.edges.flatMap((edge): PlacedEdge[] => {
    const from = placed.get(edge.from);
    const to = placed.get(edge.to);
    if (from === undefined || to === undefined) return [];
    const x1 = from.x + NODE.width;
    const y1 = from.y + NODE.height / 2;
    const x2 = to.x;
    const y2 = to.y + NODE.height / 2;
    const bend = (x2 - x1) / 2;
    return [
      {
        ...edge,
        path: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
        width: edge.tokens > 0 ? 1.5 + 8.5 * Math.sqrt(edge.tokens / most) : 1.5,
      },
    ];
  });
  const layers = Math.max(0, ...layer.values()) + 1;
  return {
    nodes: [...placed.values()],
    edges,
    width: graph.nodes.length === 0 ? 0 : NODE.pad * 2 + layers * NODE.width + (layers - 1) * NODE.gapX,
    height: graph.nodes.length === 0 ? 0 : height,
  };
}
