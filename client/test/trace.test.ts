import { describe, expect, it } from "vitest";
import { callGraph, compactDuration, compactTokens, flattenTrace, parseSlash, totalTokens, traceLines, traceTree, type Span } from "../src";

function span(id: string, parent: string | null, kind: Span["kind"], name: string, more: Partial<Span> = {}): Span {
  return {
    id,
    parent_id: parent,
    run_id: "r1",
    kind,
    name,
    detail: "",
    model: "",
    actor_id: null,
    started_ms: 1000,
    ended_ms: 2000,
    status: "ok",
    usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
    context_tokens: 0,
    first_ms: null,
    chars: 0,
    error: "",
    input: "",
    output: "",
    ...more,
  };
}

const usage = (input: number, cached: number, output: number): Span["usage"] => ({
  input_tokens: input,
  cache_read_tokens: cached,
  cache_write_tokens: 0,
  output_tokens: output,
});

const RUN: Span[] = [
  span("run", null, "run", "run", { detail: "fix the test", actor_id: "p_host", started_ms: 0, ended_ms: 9000 }),
  span("m1", "run", "llm", "turn", { model: "sonnet", usage: usage(100, 900, 50), started_ms: 0, ended_ms: 2000 }),
  span("a", "run", "agent", "explore", { model: "haiku", started_ms: 2000, ended_ms: 6000 }),
  span("am", "a", "llm", "turn", { model: "haiku", usage: usage(400, 0, 20), started_ms: 2000, ended_ms: 3000 }),
  span("at", "a", "tool", "grep", { detail: "alpha", started_ms: 3000, ended_ms: 3400, status: "error" }),
  span("t", "run", "tool", "bash", { detail: "pytest", started_ms: 6000, ended_ms: 8000 }),
  span("ap", "t", "approval", "approval", { actor_id: "p_host", started_ms: 6000, ended_ms: 7500 }),
];

describe("a run's trace", () => {
  it("is a tree whose nodes add up what is under them", () => {
    const root = traceTree(RUN)[0]!;
    expect(root.children.map((child) => child.span.id)).toEqual(["m1", "a", "t"]);
    expect(totalTokens(root.totals)).toBe(1050 + 420);
    expect(root.totals).toMatchObject({ models: 2, tools: 3, cached: 900 });
    const agent = root.children[1]!;
    expect(totalTokens(agent.totals)).toBe(420);
    expect(agent.durationMs).toBe(4000);
    expect(flattenTrace([root]).map((node) => node.depth)).toEqual([0, 1, 1, 2, 2, 1, 2]);
  });

  it("measures a span still running up to now, and roots a span whose parent is missing", () => {
    const open = span("x", "gone", "tool", "bash", { started_ms: 1000, ended_ms: null, status: "running" });
    const root = traceTree([open], 4000)[0]!;
    expect(root.durationMs).toBe(3000);
    expect(root.depth).toBe(0);
  });

  it("draws as a tree with what each node spent", () => {
    const lines = traceLines(traceTree(RUN));
    expect(lines.map((line) => `${line.branch}${line.title}`)).toEqual([
      "run",
      "├─ model",
      "├─ agent · explore",
      "│  ├─ model",
      "│  └─ tool · grep",
      "└─ tool · bash",
      "   └─ waited for approval",
    ]);
    expect(lines[0]).toMatchObject({ detail: "fix the test", tokens: "1.5k", duration: "9.0s", share: 1 });
    expect(lines[1]).toMatchObject({ detail: "sonnet", tokens: "1.1k" });
    expect(lines[4]).toMatchObject({ detail: "alpha", tokens: "", status: "error" });
  });

  it("adds up who called what across runs", () => {
    const graph = callGraph(RUN, (id) => (id === "p_host" ? "Tamirlan" : id));
    const byId = Object.fromEntries(graph.nodes.map((node) => [node.id, node]));
    expect(byId["person:p_host"]).toMatchObject({ label: "Tamirlan", calls: 1, tokens: 1470 });
    expect(byId["agent:main"]).toMatchObject({ calls: 1, tokens: 1470 });
    expect(byId["agent:explore"]).toMatchObject({ calls: 1, tokens: 420 });
    expect(byId["model:haiku"]).toMatchObject({ calls: 1, tokens: 420 });
    expect(byId["tool:grep"]).toMatchObject({ calls: 1, failed: 1 });
    const edges = graph.edges.map((edge) => `${edge.from}>${edge.to}`);
    expect(edges).toEqual([
      "person:p_host>agent:main",
      "agent:main>model:sonnet",
      "agent:main>agent:explore",
      "agent:explore>model:haiku",
      "agent:explore>tool:grep",
      "agent:main>tool:bash",
    ]);
  });

  it("writes tokens and time compactly", () => {
    expect([999, 1234, 15_400, 1_250_000].map(compactTokens)).toEqual(["999", "1.2k", "15k", "1.3M"]);
    expect([850, 3200, 42_000, 72_000, 120_000].map(compactDuration)).toEqual(["850ms", "3.2s", "42s", "1m12s", "2m"]);
  });

  it("is asked for with /trace", () => {
    expect(parseSlash("/trace")).toEqual({ type: "trace.get", run_id: null, everything: false });
    expect(parseSlash("/trace all")).toEqual({ type: "trace.get", run_id: null, everything: true });
  });
});
