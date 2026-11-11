import { expect, test } from "vitest";
import { absorb, emptyFeed, Projection, type Event } from "../src";

const usage = { cache_read_tokens: 0, cache_write_tokens: 0, input_tokens: 0, output_tokens: 0 };
const ended = (reason: "error" | "limit" | "aborted", error: string | null) =>
  ({ type: "run.ended", run_id: "r1", reason, error, usage }) as unknown as Event;

test("a run the provider failed is marked so a host can pick another agent", () => {
  const feed = absorb(emptyFeed(), ended("error", "credit balance is too low"), new Projection());
  const notice = feed.items.at(-1);
  expect(notice).toMatchObject({ kind: "notice", tone: "danger", action: "agent", text: "run failed: credit balance is too low" });
});

test("a run stopped by a limit or by a person is not the agent's fault", () => {
  const limited = absorb(emptyFeed(), ended("limit", null), new Projection()).items.at(-1);
  const aborted = absorb(emptyFeed(), ended("aborted", null), new Projection()).items.at(-1);
  expect(limited).not.toHaveProperty("action");
  expect(aborted).not.toHaveProperty("action");
});
