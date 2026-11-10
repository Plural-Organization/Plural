import { describe, expect, test } from "bun:test";
import type { Projection, Span } from "@plural/client";
import type { Row } from "../src/components/Tray";
import { callGraphRows, traceRows } from "../src/trays";

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
    started_ms: 0,
    ended_ms: 1000,
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

const SPANS: Span[] = [
  span("run", null, "run", "run", { detail: "fix the test", actor_id: "p_host", ended_ms: 9000 }),
  span("m1", "run", "llm", "turn", {
    model: "sonnet",
    usage: { input_tokens: 100, cache_read_tokens: 900, cache_write_tokens: 0, output_tokens: 50 },
    ended_ms: 2000,
  }),
  span("a", "run", "agent", "explore", { detail: "where is alpha?", started_ms: 2000, ended_ms: 6000 }),
  span("am", "a", "llm", "turn", {
    model: "haiku",
    usage: { input_tokens: 400, cache_read_tokens: 0, cache_write_tokens: 0, output_tokens: 20 },
    started_ms: 2000,
    ended_ms: 3000,
  }),
  span("t", "run", "tool", "bash", { detail: "pytest -q", started_ms: 6000, ended_ms: 8000, status: "error" }),
  span("ap", "t", "approval", "approval", { actor_id: "p_host", started_ms: 6000, ended_ms: 7500 }),
];

const projection = { state: { participants: { p_host: { name: "Tamirlan" } } } } as unknown as Projection;

const width = (bit: Row[number]): string => (typeof bit === "string" ? bit : bit.text);
const text = (rows: Row[]): string[] => rows.map((row) => row.map(width).join("").trimEnd());

describe("/trace", () => {
  test("draws the run as a tree with what each step spent", () => {
    const shown = traceRows(projection, SPANS, 100);
    expect(shown.title).toBe("trace · run by Tamirlan · 1.5k tokens · 2 model calls · 2 tool calls · 9.0s");
    const lines = text(shown.rows);
    expect(lines.map((line) => line.replace(/\s{2,}/g, " | "))).toEqual([
      "run | fix the test | 1.5k ████████ | 9.0s",
      "├─ model | sonnet | 1.1k █████▊ | 2.0s | 90% cached",
      "├─ agent · explore | where is alpha? | 420 ██▎ | 4.0s",
      "│ | └─ model | haiku | 420 ██▎ | 1.0s",
      "└─ tool · bash | pytest -q | 2.0s | ✕",
      " | └─ waited for approval | 1.5s | Tamirlan",
    ]);
    // The numbers start in the same column on every row.
    const before = shown.rows.map((row) => row.slice(0, 3).reduce((sum, bit) => sum + width(bit).length, 0));
    expect(new Set(before).size).toBe(1);
  });

  test("says so when nothing was traced", () => {
    expect(text(traceRows(projection, [], 100).rows)).toEqual(["no run has been traced yet: ask the agent something first"]);
  });

  test("adds the session up into who called what", () => {
    const shown = callGraphRows(projection, SPANS);
    expect(shown.title).toBe("trace · session · 1 run · who called what");
    expect(text(shown.rows).map((line) => line.replace(/\s{2,}/g, " | "))).toEqual([
      "Tamirlan | → | main agent | 1× | 1.5k ████████",
      "main agent | → | sonnet | 1× | 1.1k █████▊",
      "main agent | → | explore | 1× | 420 ██▎",
      "explore | → | haiku | 1× | 420 ██▎",
      "main agent | → | bash | 1× | 1 failed",
    ]);
  });
});
