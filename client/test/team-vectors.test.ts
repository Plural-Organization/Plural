import { expect, test } from "vitest";
import { isTunnelHost, joinMessage, requestMessage } from "../src";
import vectors from "./fixtures/team-vectors.json";

test("the messages signed match the Python reference", () => {
  for (const item of vectors.requests) {
    const hash = item.message.split("\n").at(-1)!;
    expect(requestMessage(item.method, item.path, hash, item.timestamp, item.nonce)).toBe(item.message);
  }
  for (const item of vectors.joins) {
    expect(joinMessage(item.url, item.room, item.timestamp, item.nonce)).toBe(item.message);
  }
});

test("tunnel hosts are told apart as the Python host does", () => {
  for (const item of vectors.tunnel_hosts) {
    expect(isTunnelHost(item.host), item.host).toBe(item.tunnel);
  }
});
