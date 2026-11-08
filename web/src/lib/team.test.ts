import { afterEach, expect, test, vi } from "vitest";
import { platformOf, reach, type Team } from "./team";

async function team(): Promise<Team> {
  const key = (await crypto.subtle.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])) as CryptoKeyPair;
  return {
    profile: { relay: "wss://relay.example.com", team_id: "t_1", team_name: "Backend", team_key: "KEY", certificate: "CERT", member: { id: "m_1", name: "alia", role: "member" } },
    key,
  };
}

const fromBase64url = (text: string) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4)), (char) => char.charCodeAt(0));

test("the browser signs with its own key and hashes with sha-256", async () => {
  const member = await team();
  const platform = platformOf(member);
  expect(await platform.sha256(new Uint8Array())).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  const signature = await platform.sign("hello");
  expect(await crypto.subtle.verify("Ed25519", member.key.publicKey, fromBase64url(signature), new TextEncoder().encode("hello"))).toBe(true);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a page asks plainly first and past the ngrok warning only when that fails", async () => {
  const seen: Array<Record<string, string>> = [];
  vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
    seen.push((init.headers ?? {}) as Record<string, string>);
    if (seen.length === 1) throw new TypeError("Failed to fetch");
    return new Response("{}");
  });
  const response = await reach("https://relay.example/teams/join", { method: "POST", headers: { "content-type": "application/json" } });
  expect(response.ok).toBe(true);
  expect(seen).toEqual([{ "content-type": "application/json" }, { "content-type": "application/json", "ngrok-skip-browser-warning": "1" }]);
});

test("a relay that stays out of reach is named in the error", async () => {
  vi.stubGlobal("fetch", async () => {
    throw new TypeError("Failed to fetch");
  });
  await expect(reach("https://relay.example/teams/join", {})).rejects.toThrow("could not reach the team's relay at relay.example");
});

test("a relay that answers plainly is asked once", async () => {
  const fetcher = vi.fn(async () => new Response("{}"));
  vi.stubGlobal("fetch", fetcher);
  await reach("https://relay.example/teams/join", {});
  expect(fetcher).toHaveBeenCalledTimes(1);
});
