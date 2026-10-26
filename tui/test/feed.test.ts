import { describe, expect, test } from "vitest";
import { Projection, emptyState, type Event, type EventRecord } from "@plural/client";
import { absorb, emptyFeed, type Feed } from "../src/feed";
import { committableEnd, tailLines } from "../src/lib/blocks";

const HOST = { id: "p_host", name: "vlad", role: "host", connected: true } as const;
const ALIA = { id: "p_alia", name: "Alia", role: "participant", connected: true } as const;
const CALL = { id: "t1", name: "bash", risk: "exec", subject: "ls -la", args: {} } as const;
const DIRECT = { initiator_id: "p_alia", initiator_role: "participant", origin: "direct" } as const;

function replay(...events: Event[]): { feed: Feed; projection: Projection } {
  const projection = new Projection();
  let feed = emptyFeed();
  events.forEach((event, index) => {
    if (event.type === "message.delta" || event.type === "session.snapshot") {
      if (event.type === "session.snapshot") {
        projection.load(event.state, event.streaming);
      } else {
        projection.observe(event);
      }
    } else {
      const record: EventRecord = {
        seq: index + 1,
        id: `e${index}`,
        ts: "2026-10-26T12:00:00Z",
        actor_id: null,
        event,
      };
      projection.apply(record);
    }
    feed = absorb(feed, event, projection);
  });
  return { feed, projection };
}

const joined = (participant: typeof HOST | typeof ALIA): Event => ({ type: "participant.joined", participant });
const delta = (text: string): Event => ({ type: "message.delta", message_id: "m1", text, thinking: false });

describe("block splitting", () => {
  test("a block is committable only after its blank line", () => {
    expect(committableEnd("first paragraph", 0)).toBe(0);
    expect(committableEnd("first paragraph\n\nsecond", 0)).toBe("first paragraph\n\n".length);
  });

  test("a blank line inside a code fence does not end the block", () => {
    const text = "intro\n\n```py\nx = 1\n\ny = 2\n```\n\nafter";
    const end = committableEnd(text, 0);
    expect(text.slice(0, end)).toBe("intro\n\n```py\nx = 1\n\ny = 2\n```\n\n");
  });

  test("an unclosed fence is never committed", () => {
    const text = "intro\n\n```py\nx = 1\n\ny = 2";
    expect(text.slice(0, committableEnd(text, 0))).toBe("intro\n\n");
  });

  test("the tail keeps only the lines that fit", () => {
    const view = tailLines("a\nb\nc\nd", 10, 2);
    expect(view).toEqual({ text: "c\nd", hidden: true });
    expect(tailLines("abcdef", 3, 2)).toEqual({ text: "abcdef", hidden: false });
    expect(tailLines("abcdefgh\nz", 3, 2).hidden).toBe(true);
  });
});

describe("feed", () => {
  test("a streamed reply is committed block by block and never twice", () => {
    const { feed } = replay(
      { type: "message.started", run_id: "r", message_id: "m1" },
      delta("First paragraph.\n\nSecond "),
      delta("paragraph.\n\nThird"),
      { type: "message.ended", run_id: "r", message_id: "m1", text: "First paragraph.\n\nSecond paragraph.\n\nThird", thinking: "" },
    );
    const texts = feed.items.filter((item) => item.kind === "assistant").map((item) => item.text);
    expect(texts).toEqual(["First paragraph.", "Second paragraph.", "Third"]);
    const firsts = feed.items.flatMap((item) => (item.kind === "assistant" ? [item.first] : []));
    expect(firsts).toEqual([true, false, false]);
    expect(feed.pending).toBeNull();
  });

  test("an unstreamed reply is committed whole", () => {
    const { feed } = replay({ type: "message.ended", run_id: "r", message_id: "m9", text: "Hello", thinking: "" });
    expect(feed.items).toMatchObject([{ kind: "assistant", text: "Hello", first: true }]);
  });

  test("a tool lives in the running list until it ends", () => {
    const started = replay({ type: "tool.started", run_id: "r", call: CALL });
    expect(started.feed.tools).toHaveLength(1);
    expect(started.feed.items).toHaveLength(0);

    const ended = replay(
      { type: "tool.started", run_id: "r", call: CALL },
      { type: "tool.ended", run_id: "r", call_id: "t1", ok: true, output: "a\nb", diff: null },
    );
    expect(ended.feed.tools).toHaveLength(0);
    expect(ended.feed.items).toMatchObject([{ kind: "tool", ok: true, output: "a\nb" }]);
  });

  test("approvals are announced when they are resolved", () => {
    const { feed } = replay(
      joined(HOST),
      { type: "approval.requested", approval: { id: "ap1", call: CALL, provenance: DIRECT, timeout_at: "2026-10-26T12:02:00Z", suggested_patterns: [] } },
      { type: "approval.resolved", approval_id: "ap1", decision: "once", resolved_by: "p_host" },
      { type: "approval.requested", approval: { id: "ap2", call: CALL, provenance: DIRECT, timeout_at: "2026-10-26T12:02:00Z", suggested_patterns: [] } },
      { type: "approval.resolved", approval_id: "ap2", decision: "block", resolved_by: null },
    );
    const notices = feed.items.filter((item) => item.kind === "notice");
    expect(notices.map((item) => item.text)).toEqual([
      "vlad joined as host",
      "bash ls -la: allowed (vlad)",
      "bash ls -la: blocked (timeout)",
    ]);
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

  test("a failed run is reported and clears the live state", () => {
    const { feed } = replay(
      { type: "message.started", run_id: "r", message_id: "m1" },
      delta("partial"),
      { type: "run.ended", run_id: "r", reason: "error", usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 }, error: "boom" },
    );
    expect(feed.pending).toBeNull();
    expect(feed.items.at(-1)).toMatchObject({ kind: "notice", tone: "danger", text: "run failed: boom" });
  });

  test("a snapshot fills the history once and keeps an unfinished reply live", () => {
    const state = {
      ...emptyState(),
      participants: { p_alia: ALIA },
      transcript: [
        { id: "pm1", kind: "prompt", author_id: "p_alia", text: "hi", tool: null, ok: null, output: "" },
        { id: "m0", kind: "assistant", author_id: null, text: "hello", tool: null, ok: null, output: "" },
        { id: "t1", kind: "tool", author_id: null, text: "", tool: CALL, ok: true, output: "x", },
      ],
    } as const;
    const snapshot: Event = { type: "session.snapshot", state: state as never, streaming: { m1: "typing" } };
    const first = replay(snapshot);
    expect(first.feed.items.map((item) => item.kind)).toEqual(["user", "assistant", "tool"]);
    expect(first.feed.pending).toMatchObject({ messageId: "m1", text: "typing", committed: 0 });

    const again = absorb(first.feed, snapshot, first.projection);
    expect(again.items).toHaveLength(3);
  });
});
