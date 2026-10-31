import { describe, expect, test } from "bun:test";
import { createPrivateKey } from "node:crypto";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { authorization, fetchSessions, httpBase, joinMessage, loadTeam, pickTeamSession, requestMessage, TeamWatcher, teamProof, type SessionCard, type Team } from "../src/team";

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
