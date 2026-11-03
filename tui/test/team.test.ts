import { describe, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { authorization, closedTunnel, createTeamInvite, fetchSessions, httpBase, isTunnelHost, joinMessage, leaveClosedTunnel, loadTeam, pickTeamSession, relayState, requestMessage, TeamWatcher, teamJoinCommand, teamProof, type SessionCard, type Team } from "../src/team";

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

describe("signing", () => {
  test("a request is signed exactly the way the Python host signs it", () => {
    expect(requestMessage("GET", "/teams/t_1/sessions", new Uint8Array(), 1700000000, "abcd")).toBe(
      "GET\n/teams/t_1/sessions\n1700000000\nabcd\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
    expect(authorization(team(), "GET", "/teams/t_1/sessions", new Uint8Array(), 1700000000, "abcd")).toBe(
      "Plural cert=CERT ts=1700000000 nonce=abcd sig=WuXXf4rmb2wmrtIT1rz1acQ38rfj7cZhWlaEXedZ1RCbnNiHFWEyeAxHGGAbeMOzj6TDuci-RppUPK-wIFEjDA",
    );
  });

  test("the relay address becomes an http one", () => {
    expect(httpBase("wss://r.example.com")).toBe("https://r.example.com");
    expect(httpBase("ws://127.0.0.1:8787/")).toBe("http://127.0.0.1:8787");
    expect(() => httpBase("ftp://x")).toThrow();
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

  test("the command to paste names the code and the relay", () => {
    expect(teamJoinCommand(team(), "abc123")).toBe("plural team join abc123 --relay wss://relay.example.com");
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

  test("the watcher keeps the last list when the relay is unreachable and says why", async () => {
    let up = true;
    const fetcher = (async () => {
      if (!up) {
        throw new Error("connection refused");
      }
      return new Response(JSON.stringify({ sessions: [card("alia", "r_1")] }));
    }) as unknown as typeof fetch;
    const watcher = new TeamWatcher(team(), fetcher, 60_000);
    const seen: (string | null)[] = [];
    watcher.subscribe((view) => seen.push(view.error));
    await watcher.refresh();
    expect(watcher.view.sessions).toHaveLength(1);
    up = false;
    await watcher.refresh();
    expect(watcher.view.sessions).toHaveLength(1);
    expect(watcher.view.error).toBe("connection refused");
    expect(seen).toEqual([null, "connection refused"]);
  });
});

describe("the watcher while a request is slow", () => {
  test("a second refresh does not start another request", async () => {
    let calls = 0;
    let release: () => void = () => undefined;
    const fetcher = (async () => {
      calls += 1;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return new Response(JSON.stringify({ sessions: [] }));
    }) as unknown as typeof fetch;
    const watcher = new TeamWatcher(team(), fetcher, 60_000);
    const first = watcher.refresh();
    await watcher.refresh();
    expect(calls).toBe(1);
    release();
    await first;
    const next = watcher.refresh();
    expect(calls).toBe(2);
    release();
    await next;
  });
});

describe("joining a teammate's session", () => {
  test("the proof is signed exactly the way the Python host checks it, and names the address it is for", () => {
    const proof = teamProof(team(), "wss://relay.example.com/r_live", "r_live", 1700000000, "abcd1234");
    expect(proof).toEqual({
      certificate: "CERT",
      url: "wss://relay.example.com/r_live",
      ts: 1700000000,
      nonce: "abcd1234",
      proof: "Jw7wGv6Wuf_2h8ClUCqn-L7gxHINWkyYK8tqta_tMuVKpPm-Mf9jQcMXCujFmiSm4aGQmXOmpI1FKs7WrIeIAA",
    });
    expect(joinMessage("wss://relay.example.com/r_live", "r_live", 1700000000, "abcd1234")).toBe("plural-team-join\nwss://relay.example.com/r_live\nr_live\n1700000000\nabcd1234");
  });

  const sessions = [card("alia", "r_a1"), { ...card("alia", "r_a2"), repo: "web" }, card("bek", "r_b"), card("vlad", "r_v")];

  test("@name finds the person's session, whatever the case", () => {
    expect(pickTeamSession(sessions, "m_vlad", "@BEK").room).toBe("r_b");
    expect(pickTeamSession(sessions, "m_vlad", "bek").room).toBe("r_b");
  });

  test("a person with several sessions needs the repository said", () => {
    expect(() => pickTeamSession(sessions, "m_vlad", "@alia")).toThrow("@alia:api, @alia:web");
    expect(pickTeamSession(sessions, "m_vlad", "@alia:web").room).toBe("r_a2");
    expect(() => pickTeamSession(sessions, "m_vlad", "@alia:nope")).toThrow("api, web");
  });

  test("nobody sharing, your own session and an empty name are told apart", () => {
    expect(() => pickTeamSession(sessions, "m_vlad", "@cleo")).toThrow("not sharing a session");
    expect(() => pickTeamSession(sessions, "m_vlad", "@vlad")).toThrow("your own session");
    expect(() => pickTeamSession(sessions, "m_vlad", "@")).toThrow("usage");
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

  test("only the tunnels that open for one session are told apart", () => {
    for (const host of ["calm-fox.trycloudflare.com", "a1b2.ngrok-free.app", "x.ngrok.io", "abc.loca.lt:443"]) {
      expect(isTunnelHost(host)).toBe(true);
    }
    for (const host of ["relay.plrl.host", "relay.example.com", "127.0.0.1:8787", "notngrok.io"]) {
      expect(isTunnelHost(host)).toBe(false);
    }
  });

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
