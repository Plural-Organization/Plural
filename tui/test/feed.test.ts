import { describe, expect, test } from "bun:test";
import { Projection, emptyState, type Event, type EventRecord } from "@plural/client";
import { absorb, emptyFeed, lastReply, type Feed } from "../src/feed";

const HOST = { id: "p_host", name: "vlad", role: "host", connected: true } as const;
const ALIA = { id: "p_alia", name: "Alia", role: "participant", connected: true } as const;
const CALL = { id: "t1", name: "bash", risk: "exec", subject: "ls -la", args: {} } as const;
const DIRECT = { initiator_id: "p_alia", initiator_role: "participant", origin: "direct" } as const;
const USAGE = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 };

function replay(...events: Event[]): { feed: Feed; projection: Projection } {
  const projection = new Projection();
  let feed = emptyFeed();
  events.forEach((event, index) => {
    if (event.type === "message.delta") {
      projection.observe(event);
    } else if (event.type === "session.snapshot") {
      projection.load(event.state, event.streaming);
    } else {
      const record: EventRecord = { seq: index + 1, id: `e${index}`, ts: "2026-10-26T12:00:00Z", actor_id: null, event };
      projection.apply(record);
    }
    feed = absorb(feed, event, projection);
  });
  return { feed, projection };
}

const joined = (participant: typeof HOST | typeof ALIA): Event => ({ type: "participant.joined", participant });
const delta = (text: string): Event => ({ type: "message.delta", message_id: "m1", text, thinking: false });
const started: Event = { type: "message.started", run_id: "r", message_id: "m1" };

describe("feed", () => {
  test("a streamed reply grows in place and is finalised with its full text", () => {
    const { feed } = replay(started, delta("First "), delta("paragraph."), {
      type: "message.ended",
      run_id: "r",
      message_id: "m1",
      text: "First paragraph.",
      thinking: "",
    });
    expect(feed.items).toEqual([{ kind: "assistant", id: "m1", text: "First paragraph.", streaming: false }]);
  });

  test("while streaming the item is marked live", () => {
    const { feed } = replay(started, delta("partial"));
    expect(feed.items).toEqual([{ kind: "assistant", id: "m1", text: "partial", streaming: true }]);
  });

  test("an empty reply leaves no card behind", () => {
    const { feed } = replay(started, { type: "message.ended", run_id: "r", message_id: "m1", text: "", thinking: "" });
    expect(feed.items).toEqual([]);
  });

  test("an unstreamed reply is added whole", () => {
    const { feed } = replay({ type: "message.ended", run_id: "r", message_id: "m9", text: "Hello", thinking: "" });
    expect(feed.items).toMatchObject([{ kind: "assistant", text: "Hello", streaming: false }]);
  });

  test("a tool card runs, then settles with its output", () => {
    const running = replay({ type: "tool.started", run_id: "r", call: CALL });
    expect(running.feed.items).toMatchObject([{ kind: "tool", status: "running", output: "" }]);
    const ended = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.ended", run_id: "r", call_id: "t1", ok: true, output: "a\nb", diff: null },
    );
    expect(ended.feed.items).toMatchObject([{ kind: "tool", status: "ok", output: "a\nb" }]);
  });

  test("approvals are announced when they are resolved, except for your own answers", () => {
    const request = (id: string): Event => ({
      type: "approval.requested",
      approval: { id, call: CALL, provenance: DIRECT, timeout_at: "2026-10-26T12:02:00Z", suggested_patterns: [] },
    });
    const { feed } = replay(
      joined(HOST),
      { type: "session.welcome", room: "r", token: "t", participant: HOST, base_policy: [], agent: "" },
      request("ap1"),
      { type: "approval.resolved", approval_id: "ap1", decision: "once", resolved_by: "p_host" },
      request("ap2"),
      { type: "approval.resolved", approval_id: "ap2", decision: "block", resolved_by: null },
    );
    const notices = feed.items.filter((item) => item.kind === "notice").map((item) => item.text);
    expect(notices).toContain("bash ls -la: blocked (timeout)");
    expect(feed.approvals).toEqual({});
  });

  test("a prompt shows who wrote it and whether it came through a proposal", () => {
    const { feed } = replay(joined(ALIA), {
      type: "prompt.accepted",
      prompt_id: "pm1",
      author_id: "p_alia",
      text: "hello",
      delivery: "now",
      provenance: { ...DIRECT, origin: "proposal" },
      attachments: [],
    });
    expect(feed.items.at(-1)).toMatchObject({ kind: "user", name: "Alia", role: "participant", viaProposal: true, text: "hello" });
  });

  test("a failed run settles the live items and is reported", () => {
    const { feed } = replay(
      started,
      delta("partial"),
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "run.ended", run_id: "r", reason: "error", usage: USAGE, error: "boom" },
    );
    expect(feed.items[0]).toMatchObject({ kind: "assistant", streaming: false });
    expect(feed.items[1]).toMatchObject({ kind: "tool", status: "failed" });
    expect(feed.items.at(-1)).toMatchObject({ kind: "notice", tone: "danger", text: "run failed: boom" });
  });

  test("a snapshot fills the history once and keeps an unfinished reply live", () => {
    const state = {
      ...emptyState(),
      participants: { p_alia: ALIA },
      transcript: [
        { id: "pm1", kind: "prompt", author_id: "p_alia", text: "hi", tool: null, ok: null, output: "" },
        { id: "m0", kind: "assistant", author_id: null, text: "hello", tool: null, ok: null, output: "" },
        { id: "t1", kind: "tool", author_id: null, text: "", tool: CALL, ok: true, output: "x" },
      ],
    };
    const snapshot: Event = { type: "session.snapshot", state: state as never, streaming: { m1: "typing" }, typing: [] };
    const first = replay(snapshot);
    expect(first.feed.items.map((item) => item.kind)).toEqual(["user", "assistant", "tool", "assistant"]);
    expect(first.feed.items.at(-1)).toMatchObject({ id: "m1", text: "typing", streaming: true });
    expect(absorb(first.feed, snapshot, first.projection).items).toHaveLength(4);
  });

  test("the last reply joins everything since the last prompt", () => {
    const { feed } = replay(
      joined(ALIA),
      { type: "prompt.accepted", prompt_id: "pm1", author_id: "p_alia", text: "go", delivery: "now", provenance: DIRECT, attachments: [] },
      { type: "message.ended", run_id: "r", message_id: "m1", text: "one", thinking: "" },
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "message.ended", run_id: "r", message_id: "m2", text: "two", thinking: "" },
    );
    expect(lastReply(feed)).toBe("one\n\ntwo");
  });

  test("command output grows the running card and is dropped when it ends", () => {
    const running = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.output", call_id: "t1", chunk: "one\ntwo\n" },
      { type: "tool.output", call_id: "t1", chunk: "three\n" },
    );
    expect(running.feed.items).toMatchObject([{ kind: "tool", status: "running", live: "one\ntwo\nthree\n" }]);
    const ended = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.output", call_id: "t1", chunk: "one\n" },
      { type: "tool.ended", run_id: "r", call_id: "t1", ok: true, output: "one\n[exit 0]", diff: null },
    );
    expect(ended.feed.items).toMatchObject([{ kind: "tool", status: "ok", live: "", output: "one\n[exit 0]" }]);
  });

  test("only the tail of a very long stream is kept and late output is ignored", () => {
    const flood = "x".repeat(5000);
    const { feed } = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.output", call_id: "t1", chunk: flood },
      { type: "tool.output", call_id: "t1", chunk: `${flood}end` },
    );
    const item = feed.items[0];
    expect(item?.kind === "tool" && item.live.length).toBe(8000);
    expect(item?.kind === "tool" && item.live.endsWith("end")).toBe(true);

    const late = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.ended", run_id: "r", call_id: "t1", ok: true, output: "done", diff: null },
      { type: "tool.output", call_id: "t1", chunk: "stray\n" },
    );
    expect(late.feed.items[0]).toMatchObject({ live: "" });
  });
});
