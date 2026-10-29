import { describe, expect, test } from "vitest";
import { findInFeed, stepMatch, type FeedItem } from "../src";

const items: FeedItem[] = [
  { kind: "banner", id: "banner", room: "r_1", version: "0.2.4", guestLink: null },
  { kind: "user", id: "u1", participantId: "p_a", name: "Alia", role: "participant", viaProposal: false, text: "fix the Login flow" },
  { kind: "assistant", id: "a1", text: "I will edit auth/login.py and run the tests", streaming: false },
  {
    kind: "tool",
    id: "t1",
    call: { id: "c1", name: "bash", risk: "exec", subject: "pytest tests/test_login.py -x", args: {} },
    status: "ok",
    output: "3 passed",
    diff: null,
    live: "",
  },
  {
    kind: "tool",
    id: "t2",
    call: { id: "c2", name: "edit", risk: "write", subject: "src/auth/session.py", args: {} },
    status: "ok",
    output: "",
    diff: "-    return None\n+    return token",
    live: "",
  },
  { kind: "chat", id: "m1", authorId: "p_b", name: "Bek", text: "lunch?", to: null, toName: null, mine: false, mentioned: false },
  { kind: "notice", id: "n1", tone: "dim", text: "Bek joined" },
];

describe("search in the history", () => {
  test("finds words in prompts, replies, commands, paths, output and diffs", () => {
    expect(findInFeed(items, "login")).toEqual(["u1", "a1", "t1"]);
    expect(findInFeed(items, "pytest")).toEqual(["t1"]);
    expect(findInFeed(items, "auth/session.py")).toEqual(["t2"]);
    expect(findInFeed(items, "3 passed")).toEqual(["t1"]);
    expect(findInFeed(items, "return token")).toEqual(["t2"]);
    expect(findInFeed(items, "lunch")).toEqual(["m1"]);
  });

  test("ignores case and needs every word", () => {
    expect(findInFeed(items, "LOGIN edit")).toEqual(["a1"]);
    expect(findInFeed(items, "login nothing")).toEqual([]);
  });

  test("an empty query finds nothing and the banner is never a match", () => {
    expect(findInFeed(items, "  ")).toEqual([]);
    expect(findInFeed(items, "0.2.4")).toEqual([]);
  });

  test("stepping wraps around both ways", () => {
    expect(stepMatch(3, 2, 1)).toBe(0);
    expect(stepMatch(3, 0, -1)).toBe(2);
    expect(stepMatch(0, 0, 1)).toBe(0);
  });
});
