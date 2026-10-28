import { expect, test } from "vitest";
import { parseLink, parseSlash, SlashError } from "../src";

test("an invite link is split into url, room and invite", () => {
  expect(parseLink("ws://127.0.0.1:7777/r_1?invite=abc")).toEqual({
    url: "ws://127.0.0.1:7777/r_1",
    room: "r_1",
    invite: "abc",
    token: null,
    join: null,
  });
});

test("a room link keeps its join code", () => {
  expect(parseLink("wss://abc.ngrok-free.app/r_1?join=CODE-1")).toEqual({
    url: "wss://abc.ngrok-free.app/r_1",
    room: "r_1",
    invite: null,
    token: null,
    join: "CODE-1",
  });
});

test("a token link keeps the token", () => {
  expect(parseLink("wss://relay.example.com/r_9/?token=t1")).toEqual({
    url: "wss://relay.example.com/r_9/",
    room: "r_9",
    invite: null,
    token: "t1",
    join: null,
  });
});

test.each(["http://example.com/r_1", "not a link", "ws://host/"])("%s is refused", (raw) => {
  expect(() => parseLink(raw)).toThrow();
});

test("slash commands become protocol commands", () => {
  expect(parseSlash("just a prompt")).toBeNull();
  expect(parseSlash("/abort")).toEqual({ type: "run.abort" });
  expect(parseSlash("/compact")).toEqual({ type: "context.compact" });
  expect(parseSlash("/policy")).toEqual({ type: "show.policy" });
  expect(parseSlash("/policy allow bash make *")).toEqual({
    type: "policy.add",
    tool: "bash",
    pattern: "make *",
    action: "allow",
  });
  expect(parseSlash("/policy rm pl_1")).toEqual({ type: "policy.remove", rule_id: "pl_1" });
  expect(parseSlash("/mode review")).toEqual({ type: "session.set_prompt_mode", mode: "review" });
});

test.each([
  "/nope",
  "/policy allow",
  "/policy allow bash",
  "/policy permit bash x",
  "/policy rm",
  "/mode",
  "/mode closed",
])("%s is a slash error", (text) => {
  expect(() => parseSlash(text)).toThrow(SlashError);
});
