import { describe, expect, it } from "vitest";
import type { CallGraph } from "@plural/client";
import { layoutGraph, NODE } from "./traceGraph";

const node = (id: string, kind: CallGraph["nodes"][number]["kind"], tokens = 0) => ({ id, kind, label: id, calls: 1, tokens, durationMs: 0, failed: 0 });

const GRAPH: CallGraph = {
  nodes: [node("p", "person", 900), node("main", "agent", 900), node("sub", "agent", 300), node("sonnet", "model", 600), node("haiku", "model", 300), node("bash", "tool")],
  edges: [
    { from: "p", to: "main", calls: 1, tokens: 900 },
    { from: "main", to: "sonnet", calls: 2, tokens: 600 },
    { from: "main", to: "sub", calls: 1, tokens: 300 },
    { from: "sub", to: "haiku", calls: 1, tokens: 300 },
    { from: "main", to: "bash", calls: 3, tokens: 0 },
  ],
};

describe("the call graph's layout", () => {
  it("puts each node one column past its furthest caller", () => {
    const layout = layoutGraph(GRAPH);
    const layer = Object.fromEntries(layout.nodes.map((placed) => [placed.id, placed.layer]));
    expect(layer).toEqual({ p: 0, main: 1, sub: 2, sonnet: 2, bash: 2, haiku: 3 });
    expect(layout.width).toBe(NODE.pad * 2 + 4 * NODE.width + 3 * NODE.gapX);
  });

  it("stacks a column without overlap, agents above models above tools", () => {
    const layout = layoutGraph(GRAPH);
    const third = layout.nodes.filter((placed) => placed.layer === 2).sort((a, b) => a.y - b.y);
    expect(third.map((placed) => placed.id)).toEqual(["sub", "sonnet", "bash"]);
    expect(third[1]!.y - third[0]!.y).toBe(NODE.height + NODE.gapY);
    expect(layout.height).toBe(NODE.pad * 2 + 3 * NODE.height + 2 * NODE.gapY);
  });

  it("draws every edge to the right, thicker for more tokens", () => {
    const layout = layoutGraph(GRAPH);
    const width = Object.fromEntries(layout.edges.map((edge) => [`${edge.from}>${edge.to}`, edge.width]));
    expect(width["p>main"]).toBe(10);
    expect(width["main>bash"]).toBe(1.5);
    expect(width["main>sonnet"]!).toBeGreaterThan(width["main>sub"]!);
    expect(layout.edges.every((edge) => edge.path.startsWith("M "))).toBe(true);
  });

  it("is empty for an empty graph and survives a cycle", () => {
    expect(layoutGraph({ nodes: [], edges: [] })).toEqual({ nodes: [], edges: [], width: 0, height: 0 });
    const loop: CallGraph = { nodes: [node("a", "agent"), node("b", "agent")], edges: [{ from: "a", to: "b", calls: 1, tokens: 0 }, { from: "b", to: "a", calls: 1, tokens: 0 }] };
    expect(layoutGraph(loop).nodes).toHaveLength(2);
  });
});
