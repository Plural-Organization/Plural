import { createPrivateKey } from "node:crypto";
import { expect, test } from "bun:test";
import { authorization, isTunnelHost, joinMessage, requestMessage, teamProof } from "@plural/client";
import { platformOf, type Team } from "../src/team";
import vectors from "../../client/test/fixtures/team-vectors.json";

const team: Team = {
  profile: {
    relay: "wss://relay.example.com",
    team_id: "t_1",
    team_name: "Backend",
    team_key: "KEY",
    certificate: vectors.certificate,
    member: { id: vectors.identity.member_id, name: "alia", role: "member" },
  },
  key: createPrivateKey({ key: Buffer.from(vectors.identity.pkcs8_hex, "hex"), format: "der", type: "pkcs8" }),
};

const platform = platformOf(team);
const bytes = (hex: string) => new Uint8Array(Buffer.from(hex, "hex"));

test("signed requests match the Python reference byte for byte", async () => {
  for (const item of vectors.requests) {
    const body = bytes(item.body_hex);
    expect(requestMessage(item.method, item.path, await platform.sha256(body), item.timestamp, item.nonce)).toBe(item.message);
    expect(await authorization(team.profile, platform, item.method, item.path, body, { timestamp: item.timestamp, nonce: item.nonce })).toBe(item.authorization);
  }
});

test("team joins match the Python reference byte for byte", async () => {
  for (const item of vectors.joins) {
    expect(joinMessage(item.url, item.room, item.timestamp, item.nonce)).toBe(item.message);
    expect(await teamProof(team.profile, platform, item.url, item.room, { timestamp: item.timestamp, nonce: item.nonce })).toEqual(item.proof);
  }
});

test("tunnel hosts are told apart as the Python host does", () => {
  for (const item of vectors.tunnel_hosts) {
    expect(isTunnelHost(item.host), item.host).toBe(item.tunnel);
  }
});
