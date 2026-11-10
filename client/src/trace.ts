import type { Span, SpanKind } from "./protocol";

export type SpanStatus = Span["status"];

/** What a span and everything under it spent. */
export interface TraceTotals {
  /** Prompt tokens sent at full price. */
  input: number;
  /** Prompt tokens the provider read from its cache. */
  cached: number;
  /** Prompt tokens the provider wrote to its cache. */
  written: number;
  output: number;
  models: number;
  tools: number;
}

export interface TraceNode {
  span: Span;
  children: TraceNode[];
  depth: number;
  /** The span's own spending plus its children's. */
  totals: TraceTotals;
  /** How long it took; for a span still running, how long so far at `now`. */
  durationMs: number;
}

/** Every token a span's requests carried, in and out. */
export function totalTokens(totals: TraceTotals): number {
  return totals.input + totals.cached + totals.written + totals.output;
}

function own(span: Span): TraceTotals {
  return {
    input: span.usage.input_tokens,
    cached: span.usage.cache_read_tokens,
    written: span.usage.cache_write_tokens,
    output: span.usage.output_tokens,
    models: span.kind === "llm" ? 1 : 0,
    tools: span.kind === "tool" || span.kind === "agent" ? 1 : 0,
  };
}

function plus(a: TraceTotals, b: TraceTotals): TraceTotals {
  return {
    input: a.input + b.input,
    cached: a.cached + b.cached,
    written: a.written + b.written,
    output: a.output + b.output,
    models: a.models + b.models,
    tools: a.tools + b.tools,
  };
}

/**
 * A run's spans as trees, oldest root first. A span whose parent is missing becomes a root, so a
 * trace cut short by a limit still shows.
 */
export function traceTree(spans: readonly Span[], now: number = Date.now()): TraceNode[] {
  const known = new Set(spans.map((span) => span.id));
  const under = new Map<string, Span[]>();
  for (const span of spans) {
    const parent = span.parent_id !== null && known.has(span.parent_id) ? span.parent_id : "";
    under.set(parent, [...(under.get(parent) ?? []), span]);
  }
  const build = (span: Span, depth: number): TraceNode => {
    const children = (under.get(span.id) ?? [])
      .slice()
      .sort((a, b) => a.started_ms - b.started_ms)
      .map((child) => build(child, depth + 1));
    return {
      span,
      children,
      depth,
      totals: children.reduce((sum, child) => plus(sum, child.totals), own(span)),
      durationMs: Math.max(0, (span.ended_ms ?? now) - span.started_ms),
    };
  };
  return (under.get("") ?? [])
    .slice()
    .sort((a, b) => a.started_ms - b.started_ms)
    .map((root) => build(root, 0));
}

/** A tree's nodes in the order they are drawn, parents before their children. */
export function flattenTrace(roots: readonly TraceNode[]): TraceNode[] {
  return roots.flatMap((node) => [node, ...flattenTrace(node.children)]);
}

/** 1234 → "1.2k", 1_250_000 → "1.3M". */
export function compactTokens(count: number): string {
  if (count >= 1_000_000) {
    return `${(count / 1_000_000).toFixed(1)}M`;
  }
  if (count >= 10_000) {
    return `${Math.round(count / 1000)}k`;
  }
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
}

/** 850 → "850ms", 3200 → "3.2s", 72_000 → "1m12s". */
export function compactDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds === 0 ? `${minutes}m` : `${minutes}m${String(seconds).padStart(2, "0")}s`;
}

const KIND_WORDS: Record<SpanKind, string> = {
  run: "run",
  llm: "model",
  tool: "tool",
  approval: "approval",
  agent: "agent",
};

/** What a span is, in a few words: "model · turn", "tool · bash", "agent · explore". */
export function spanTitle(span: Span): string {
  if (span.kind === "run") {
    return span.name === "run" ? "run" : span.name;
  }
  if (span.kind === "approval") {
    return "waited for approval";
  }
  if (span.kind === "llm") {
    return span.name === "turn" ? "model" : `model · ${span.name}`;
  }
  return `${KIND_WORDS[span.kind]} · ${span.name}`;
}

/** The share of a model call's prompt that came from the provider's cache, or null without one. */
export function cachedShare(totals: TraceTotals): number | null {
  const prompt = totals.input + totals.cached + totals.written;
  return prompt > 0 ? totals.cached / prompt : null;
}

export interface TraceLine {
  node: TraceNode;
  /** The tree's branch lines before the title: "│  ├─ ". */
  branch: string;
  title: string;
  /** The model for a model call, the subject for a tool call, the prompt for a run. */
  detail: string;
  tokens: string;
  duration: string;
  status: SpanStatus;
  /** This node's share of its root's tokens, for a bar. */
  share: number;
}

/** A trace as the lines of a tree drawn with box characters, with what each node spent. */
export function traceLines(roots: readonly TraceNode[]): TraceLine[] {
  const lines: TraceLine[] = [];
  const walk = (node: TraceNode, prefix: string, last: boolean, root: TraceNode): void => {
    const whole = totalTokens(root.totals);
    const mine = totalTokens(node.totals);
    lines.push({
      node,
      branch: node.depth === 0 ? "" : `${prefix}${last ? "└─ " : "├─ "}`,
      title: spanTitle(node.span),
      detail: node.span.kind === "llm" ? node.span.model : node.span.detail,
      tokens: mine > 0 ? compactTokens(mine) : "",
      duration: compactDuration(node.durationMs),
      status: node.span.status,
      share: whole > 0 ? mine / whole : 0,
    });
    const next = node.depth === 0 ? "" : `${prefix}${last ? "   " : "│  "}`;
    node.children.forEach((child, index) => walk(child, next, index === node.children.length - 1, root));
  };
  for (const root of roots) {
    walk(root, "", true, root);
  }
  return lines;
}

export type GraphNodeKind = "person" | "agent" | "model" | "tool";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  /** How many times it was called, or for a person how many runs they started. */
  calls: number;
  /** Tokens spent in it: a model's own, an agent's whole work, a person's runs. */
  tokens: number;
  durationMs: number;
  failed: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  calls: number;
  tokens: number;
}

export interface CallGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

const MAIN_AGENT = "agent:main";

/**
 * Who called what across the given spans, added up: people start runs of the main agent, an
 * agent calls models, tools and sub-agents. One node per person, agent, model and tool.
 */
export function callGraph(spans: readonly Span[], names: (actorId: string) => string = (id) => id): CallGraph {
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, GraphEdge>();
  const node = (id: string, kind: GraphNodeKind, label: string): GraphNode => {
    const found = nodes.get(id) ?? { id, kind, label, calls: 0, tokens: 0, durationMs: 0, failed: 0 };
    nodes.set(id, found);
    return found;
  };
  const edge = (from: string, to: string, tokens: number): void => {
    const key = `${from}\u0000${to}`;
    const found = edges.get(key) ?? { from, to, calls: 0, tokens: 0 };
    found.calls += 1;
    found.tokens += tokens;
    edges.set(key, found);
  };
  const visit = (current: TraceNode, owner: string): void => {
    const span = current.span;
    const tokens = totalTokens(current.totals);
    const failed = span.status === "error" || span.status === "denied" ? 1 : 0;
    let inside = owner;
    if (span.kind === "run") {
      const main = node(MAIN_AGENT, "agent", "main agent");
      main.calls += 1;
      main.tokens += tokens;
      main.durationMs += current.durationMs;
      main.failed += failed;
      if (span.actor_id) {
        const person = node(`person:${span.actor_id}`, "person", names(span.actor_id));
        person.calls += 1;
        person.tokens += tokens;
        edge(person.id, MAIN_AGENT, tokens);
      }
      inside = MAIN_AGENT;
    } else if (span.kind === "agent") {
      const agent = node(`agent:${span.name}`, "agent", span.name);
      agent.calls += 1;
      agent.tokens += tokens;
      agent.durationMs += current.durationMs;
      agent.failed += failed;
      edge(owner, agent.id, tokens);
      inside = agent.id;
    } else if (span.kind === "llm") {
      const label = span.model || "model";
      const model = node(`model:${label}`, "model", label);
      model.calls += 1;
      model.tokens += tokens;
      model.durationMs += current.durationMs;
      model.failed += failed;
      edge(owner, model.id, tokens);
    } else if (span.kind === "tool") {
      const tool = node(`tool:${span.name}`, "tool", span.name);
      tool.calls += 1;
      tool.durationMs += current.durationMs;
      tool.failed += failed;
      edge(owner, tool.id, 0);
    }
    for (const child of current.children) {
      visit(child, inside);
    }
  };
  for (const root of traceTree(spans)) {
    visit(root, MAIN_AGENT);
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}
