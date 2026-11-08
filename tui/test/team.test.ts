import { describe, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { closedTunnel, type SessionCard } from "@plural/client";
import { createTeamInvite, fetchSessions, leaveClosedTunnel, leaveTeam, loadTeam, platformOf, relayState, teamProof, type Team } from "../src/team";

const PEM = "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f\n-----END PRIVATE KEY-----\n";

const profile = {
  relay: "wss://relay.example.com",
  team_id: "t_1",
  team_name: "Backend",
  team_key: "k",
  certificate: "CERT",
  member: { id: "m_vlad", name: "vlad", role: "owner" },
};

const team = (): Team => ({ profile, key: createPrivateKey(PEM) });

const card = (owner: string, room: string): SessionCard => ({
  room,
  repo: "api",
  branch: "main",
  title: null,
  status: "idle",
  viewers: 0,
  endpoints: [{ kind: "relay", url: `wss://relay.example.com/${room}` }],
  owner,
  owner_id: `m_${owner}`,
  updated_at: "2026-10-29T12:00:00Z",
});

describe("the platform", () => {
  test("signs with the machine's key and hashes with sha256", async () => {
    const platform = platformOf(team());
    expect(await platform.sha256(new Uint8Array())).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect((await platform.sign("hello")).length).toBe(86);
  });

  test("names the TypeScript client and gives a request a deadline", async () => {
    let seen: RequestInit = {};
    const platform = platformOf(
      team(),
      (async (_url: string, init: RequestInit) => {
        seen = init;
        return new Response("{}");
      }) as unknown as typeof fetch,
    );
    await platform.fetch("https://relay.example.com/x", { method: "GET", headers: { authorization: "a" } });
    expect(seen.headers).toEqual({ authorization: "a", "user-agent": "plural-client" });
    expect(seen.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("the team on this machine", () => {
  test("is read from the data folder, and is absent when there is none", () => {
    const directory = mkdtempSync(join(tmpdir(), "plural-team-"));
    expect(loadTeam(directory)).toBeNull();
    writeFileSync(join(directory, "team.json"), JSON.stringify(profile));
    expect(loadTeam(directory)).toBeNull();
    writeFileSync(join(directory, "identity.pem"), PEM);
    expect(loadTeam(directory)?.profile.team_name).toBe("Backend");
    writeFileSync(join(directory, "team.json"), "{not json");
    expect(loadTeam(directory)).toBeNull();
  });
});

describe("inviting to the team", () => {
  test("asks the relay with a signed POST and returns the code", async () => {
    const seen: { url: string; method: string; header: string }[] = [];
    const fetcher = (async (url: string, init: RequestInit) => {
      seen.push({ url, method: init.method as string, header: (init.headers as Record<string, string>)["authorization"] as string });
      return new Response(JSON.stringify({ code: "abc123", expires_at: "2026-10-31T13:00:00Z" }));
    }) as unknown as typeof fetch;
    const invite = await createTeamInvite(team(), fetcher);
    expect(invite.code).toBe("abc123");
    expect(seen[0]?.url).toBe("https://relay.example.com/teams/t_1/invites");
    expect(seen[0]?.method).toBe("POST");
    expect(seen[0]?.header.startsWith("Plural cert=CERT ts=")).toBe(true);
  });

  test("a refusal carries the relay's reason", async () => {
    const fetcher = (async () => new Response(JSON.stringify({ error: "only the owner can invite" }), { status: 403 })) as unknown as typeof fetch;
    await expect(createTeamInvite(team(), fetcher)).rejects.toThrow("only the owner");
  });

});

describe("the directory calls", () => {
  // A relay run with --clients-only refuses anything that does not call itself a Plural client.
  test("name the TypeScript client to the relay", async () => {
    const agents: string[] = [];
    const fetcher = (async (_url: string, init: RequestInit) => {
      agents.push((init.headers as Record<string, string>)["user-agent"] as string);
      return new Response(JSON.stringify({ sessions: [], code: "abc123", expires_at: null }));
    }) as unknown as typeof fetch;
    await fetchSessions(team(), fetcher);
    await createTeamInvite(team(), fetcher);
    expect(agents).toEqual(["plural-client", "plural-client"]);
  });
});

describe("the list of sessions", () => {
  test("is asked from the relay with a signed request", async () => {
    const seen: { url: string; header: string }[] = [];
    const fetcher = (async (url: string, init: RequestInit) => {
      seen.push({ url, header: (init.headers as Record<string, string>)["authorization"] as string });
      return new Response(JSON.stringify({ sessions: [card("alia", "r_1")] }));
    }) as unknown as typeof fetch;
    const sessions = await fetchSessions(team(), fetcher);
    expect(sessions.map((entry) => entry.owner)).toEqual(["alia"]);
    expect(seen[0]?.url).toBe("https://relay.example.com/teams/t_1/sessions");
    expect(seen[0]?.header.startsWith("Plural cert=CERT ts=")).toBe(true);
  });

  test("a refusal carries the relay's reason", async () => {
    const fetcher = (async () => new Response(JSON.stringify({ error: "you are not a member of this team" }), { status: 401 })) as unknown as typeof fetch;
    await expect(fetchSessions(team(), fetcher)).rejects.toThrow("not a member");
  });

});

describe("joining a teammate's session", () => {
  test("the proof is signed exactly the way the Python host checks it, and names the address it is for", async () => {
    const proof = await teamProof(team(), "wss://relay.example.com/r_live", "r_live", { timestamp: 1700000000, nonce: "abcd1234" });
    expect(proof).toEqual({
      certificate: "CERT",
      url: "wss://relay.example.com/r_live",
      ts: 1700000000,
      nonce: "abcd1234",
      proof: "Jw7wGv6Wuf_2h8ClUCqn-L7gxHINWkyYK8tqta_tMuVKpPm-Mf9jQcMXCujFmiSm4aGQmXOmpI1FKs7WrIeIAA",
    });
  });
});

describe("a team on a tunnel", () => {
  const answering = (status: number | "offline") =>
    (async () => {
      if (status === "offline") {
        throw new TypeError("fetch failed");
      }
      return new Response(status === 200 ? '{"ok":true}' : "<html>tunnel gone</html>", { status });
    }) as unknown as typeof fetch;
  const saved = (relay: string): string => {
    const directory = mkdtempSync(join(tmpdir(), "plural-tunnel-"));
    writeFileSync(join(directory, "team.json"), JSON.stringify({ ...profile, relay }));
    writeFileSync(join(directory, "identity.pem"), PEM);
    return directory;
  };

  test("the relay is gone only when something else answers for it", async () => {
    expect(await relayState("wss://a.trycloudflare.com", answering(200))).toBe("alive");
    expect(await relayState("wss://a.trycloudflare.com", answering(530))).toBe("dead");
    expect(await relayState("wss://a.trycloudflare.com", answering("offline"))).toBe("unknown");
  });

  test("a team whose tunnel is closed is left, and says why", async () => {
    const directory = saved("wss://gone.trycloudflare.com");
    expect(await leaveClosedTunnel(directory, answering(530))).toContain("you left Backend: its tunnel is closed");
    expect(existsSync(join(directory, "team.json"))).toBe(false);
  });

  test("a team is kept when its tunnel answers, when this machine is offline, or when it is no tunnel", async () => {
    for (const [relay, fetcher] of [
      ["wss://up.trycloudflare.com", answering(200)],
      ["wss://gone.trycloudflare.com", answering("offline")],
      ["wss://relay.example.com", answering(530)],
    ] as const) {
      const directory = saved(relay);
      expect(await leaveClosedTunnel(directory, fetcher)).toBeNull();
      expect(existsSync(join(directory, "team.json"))).toBe(true);
    }
  });

  test("a closed tunnel is named, not shown as a relay answer", async () => {
    const gone = { ...team(), profile: { ...profile, relay: "wss://gone.trycloudflare.com" } };
    const fetcher = answering(530);
    await expect(fetchSessions(gone, fetcher)).rejects.toThrow(closedTunnel("gone.trycloudflare.com"));
    await expect(createTeamInvite(gone, fetcher)).rejects.toThrow("is closed");
    await expect(fetchSessions(team(), fetcher)).rejects.toThrow("the relay answered 530");
  });
});

describe("leaving a team", () => {
  const kept = (): string => {
    const directory = mkdtempSync(join(tmpdir(), "plural-leave-"));
    writeFileSync(join(directory, "team.json"), JSON.stringify(profile));
    writeFileSync(join(directory, "identity.pem"), PEM);
    return directory;
  };
  const relay = (outcome: number | "offline", seen: string[] = []) =>
    (async (url: string, init: RequestInit) => {
      seen.push(`${init.method} ${new URL(url).pathname}`);
      if (outcome === "offline") {
        throw new DOMException("timed out", "TimeoutError");
      }
      return outcome === 204 ? new Response(null, { status: 204 }) : new Response(JSON.stringify(outcome === 200 ? { id: "m_vlad" } : { error: "refused" }), { status: outcome });
    }) as unknown as typeof fetch;
  const member = (): Team => ({ ...team(), profile: { ...profile, member: { id: "m_alia", name: "alia", role: "member" } } });

  test("a member leaves by removing themselves, an owner deletes the team, and the profile goes", async () => {
    for (const [who, outcome, request] of [
      [member(), 200, "DELETE /teams/t_1/members/m_alia"],
      [team(), 204, "DELETE /teams/t_1"],
    ] as const) {
      const directory = kept();
      const seen: string[] = [];
      await leaveTeam(who, directory, relay(outcome, seen));
      expect(seen).toEqual([request]);
      expect(existsSync(join(directory, "team.json"))).toBe(false);
    }
  });

  test("a relay that no longer knows this member leaves nothing to undo, so the profile goes", async () => {
    for (const status of [401, 404]) {
      const directory = kept();
      await leaveTeam(member(), directory, relay(status));
      expect(existsSync(join(directory, "team.json"))).toBe(false);
    }
  });

  test("a relay that fails or does not answer keeps the profile, so leaving can be tried again", async () => {
    for (const outcome of [500, 403, "offline"] as const) {
      const directory = kept();
      await expect(leaveTeam(member(), directory, relay(outcome))).rejects.toThrow();
      expect(existsSync(join(directory, "team.json"))).toBe(true);
    }
  });
});
