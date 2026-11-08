import { expect, test } from "vitest";
import vectors from "../../../client/test/fixtures/team-vectors.json";
import { authorization, joinMessage, requestMessage, teamProof } from "@plural/client";
import { platformOf, type Team } from "./team";
import { sha256 } from "./sha256";

const bytes = (hex: string) => Uint8Array.from(hex.match(/../g) ?? [], (pair) => parseInt(pair, 16));

const profile = {
  relay: "wss://relay.example.com",
  team_id: "t_1",
  team_name: "Backend",
  team_key: "KEY",
  certificate: vectors.certificate,
  member: { id: vectors.identity.member_id, name: "alia", role: "member" },
};

async function team(): Promise<Team> {
  const privateKey = await crypto.subtle.importKey("pkcs8", bytes(vectors.identity.pkcs8_hex), { name: "Ed25519" }, false, ["sign"]);
  return { profile, key: { privateKey, publicKey: privateKey } as CryptoKeyPair };
}

test("signed requests match the Python reference byte for byte", async () => {
  const member = platformOf(await team());
  for (const item of vectors.requests) {
    const body = bytes(item.body_hex);
    expect(requestMessage(item.method, item.path, await sha256(body), item.timestamp, item.nonce)).toBe(item.message);
    expect(await authorization(profile, member, item.method, item.path, body, { timestamp: item.timestamp, nonce: item.nonce })).toBe(item.authorization);
  }
});

test("team joins match the Python reference byte for byte", async () => {
  const member = platformOf(await team());
  for (const item of vectors.joins) {
    expect(joinMessage(item.url, item.room, item.timestamp, item.nonce)).toBe(item.message);
    expect(await teamProof(profile, member, item.url, item.room, { timestamp: item.timestamp, nonce: item.nonce })).toEqual(item.proof);
  }
});
