import { describe, expect, test } from "vitest";
import { blockedByMixedContent, browserJoinLink, hostOf, unwrapLink } from "./links";

const INVITE = "ws://127.0.0.1:7777/r_1?invite=abc";

describe("unwrapLink", () => {
  test("keeps a plain invite", () => {
    expect(unwrapLink(`  ${INVITE} `)).toBe(INVITE);
  });

  test("strips the terminal command and quotes", () => {
    expect(unwrapLink(`plural join "${INVITE}"`)).toBe(INVITE);
  });

  test("reads the invite out of a browser link", () => {
    expect(unwrapLink(browserJoinLink(INVITE, { origin: "https://plural.dev", pathname: "/" }))).toBe(INVITE);
  });
});

test("hostOf shows the host of a link and falls back to the raw text", () => {
  expect(hostOf("wss://relay.example.com/r_1")).toBe("relay.example.com");
  expect(hostOf("not a url")).toBe("not a url");
});

test("a https page cannot open a plain ws link", () => {
  expect(blockedByMixedContent(INVITE, "https:")).toBe(true);
  expect(blockedByMixedContent(INVITE, "http:")).toBe(false);
  expect(blockedByMixedContent("wss://relay.example.com/r_1", "https:")).toBe(false);
});

test("a room link with its own join code goes through the browser link and comes back whole", () => {
  const room = "wss://abc.ngrok-free.app/r_01ABC?join=CODE_123-xyz";
  const page = browserJoinLink(room, { origin: "https://plural.example", pathname: "/" });
  expect(unwrapLink(page)).toBe(room);
  expect(unwrapLink(`plural join "${room}"`)).toBe(room);
});
