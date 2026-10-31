import { expect, test } from "vitest";
import { authorization, base64url, certificateWindow, httpBase, joinMessage, parseTeamInvite, renewalDue, reachable, requestMessage, teamJoinCommand, teamJoinLink, teamProof, type SessionCard, type Team, type TeamProfile } from "./team";

const PROFILE: TeamProfile = {
  relay: "wss://relay.example.com",
  team_id: "t_1",
  team_name: "Backend",
  team_key: "KEY",
  certificate: "CERT",
  member: { id: "m_1", name: "alia", role: "member" },
};

async function team(): Promise<Team> {
  const key = (await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])) as CryptoKeyPair;
  return { profile: PROFILE, key };
}

const fromBase64url = (text: string) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4)), (char) => char.charCodeAt(0));

test("an invite is the terminal's command or this page's link", () => {
  expect(parseTeamInvite("plural team join tm-7f3k9-xq2m4 --relay wss://relay.example.com")).toEqual({ code: "tm-7f3k9-xq2m4", relay: "wss://relay.example.com" });
  expect(parseTeamInvite("  $ plural team join tm-1 --relay=wss://r.example ")).toEqual({ code: "tm-1", relay: "wss://r.example" });
  expect(parseTeamInvite("https://plural-room.vercel.app/?team=tm-2&relay=wss%3A%2F%2Fr.example")).toEqual({ code: "tm-2", relay: "wss://r.example" });
  expect(parseTeamInvite("wss://host/r_1?join=abc")).toBeNull();
  expect(parseTeamInvite("hello")).toBeNull();
});

test("the invite the owner shares names the code and the relay", () => {
  expect(teamJoinCommand(PROFILE, "tm-1")).toBe("plural team join tm-1 --relay wss://relay.example.com");
  expect(teamJoinLink(PROFILE, "tm-1", { origin: "https://plural-room.vercel.app", pathname: "/" })).toBe(
    "https://plural-room.vercel.app/?team=tm-1&relay=wss%3A%2F%2Frelay.example.com",
  );
  expect(parseTeamInvite(teamJoinLink(PROFILE, "tm-1", { origin: "https://p.example", pathname: "/" }))).toEqual({ code: "tm-1", relay: PROFILE.relay });
});

test("the relay's http address follows its websocket one", () => {
  expect(httpBase("wss://relay.example.com/")).toBe("https://relay.example.com");
  expect(httpBase("ws://127.0.0.1:8787")).toBe("http://127.0.0.1:8787");
  expect(() => httpBase("ftp://x")).toThrow("is not a relay address");
});

test("a signed request carries the certificate and a signature over method, path, time, nonce and body", async () => {
  const member = await team();
  const header = await authorization(member, "get", "/teams/t_1/sessions", new Uint8Array(), 1_700_000_000);
  const fields = Object.fromEntries(header.replace(/^Plural /, "").split(" ").map((part) => part.split("=") as [string, string]));
  expect(fields.cert).toBe("CERT");
  expect(fields.ts).toBe("1700000000");
  const empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
  const message = new TextEncoder().encode(requestMessage("GET", "/teams/t_1/sessions", empty, 1_700_000_000, fields.nonce!));
  expect(await crypto.subtle.verify("Ed25519", member.key.publicKey, fromBase64url(fields.sig!), message)).toBe(true);
});

test("a team join proves the key for this room at this address", async () => {
  const member = await team();
  const proof = await teamProof(member, "wss://relay.example.com/r_1", "r_1", 1_700_000_000);
  expect(proof.certificate).toBe("CERT");
  const message = new TextEncoder().encode(joinMessage("wss://relay.example.com/r_1", "r_1", 1_700_000_000, proof.nonce));
  expect(await crypto.subtle.verify("Ed25519", member.key.publicKey, fromBase64url(proof.proof), message)).toBe(true);
});

test("a certificate is renewed near its end, never right after it was made", () => {
  const cert = (iat: string, exp: string) => `${base64url(new TextEncoder().encode(JSON.stringify({ iat, exp })))}.sig`;
  const month = cert("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z");
  expect(certificateWindow(month)).toEqual({ issued: Date.parse("2026-11-01T00:00:00Z"), expiry: Date.parse("2026-12-01T00:00:00Z") });
  expect(renewalDue(month, Date.parse("2026-11-20T00:00:00Z"))).toBe(false);
  expect(renewalDue(month, Date.parse("2026-11-25T00:00:00Z"))).toBe(true);
  // A relay that gives six days: half of it must pass first.
  const short = cert("2026-11-01T00:00:00Z", "2026-11-07T00:00:00Z");
  expect(renewalDue(short, Date.parse("2026-11-01T00:00:10Z"))).toBe(false);
  expect(renewalDue(short, Date.parse("2026-11-05T00:00:00Z"))).toBe(true);
  expect(certificateWindow("garbage")).toBeNull();
});

test("an https page opens only a wss endpoint", () => {
  const card = { endpoints: [{ kind: "direct", url: "ws://10.0.0.2:7000/r_1" }, { kind: "relay", url: "wss://relay.example.com/r_1" }] } as SessionCard;
  expect(reachable(card, "https:")).toBe("wss://relay.example.com/r_1");
  expect(reachable(card, "http:")).toBe("ws://10.0.0.2:7000/r_1");
  expect(reachable({ endpoints: [{ kind: "direct", url: "ws://10.0.0.2:7000/r_1" }] } as SessionCard, "https:")).toBeNull();
});
