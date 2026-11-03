import { describe, expect, test } from "vitest";
import {
  answer,
  authorization,
  certificateWindow,
  closedTunnel,
  createTeamInvite,
  fetchSessions,
  firstSession,
  httpBase,
  isTunnelHost,
  leaveTeamOnRelay,
  parseTeamInvite,
  pickTeamSession,
  reachable,
  renewCertificate,
  renewalDue,
  teamJoinCommand,
  teamJoinLink,
  teamProof,
  TeamWatcher,
  type SessionCard,
  type TeamPlatform,
  type TeamProfile,
} from "../src";

const PROFILE: TeamProfile = {
  relay: "wss://relay.example.com",
  team_id: "t_1",
  team_name: "Backend",
  team_key: "KEY",
  certificate: "CERT",
  member: { id: "m_vlad", name: "vlad", role: "owner" },
};

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

interface Seen {
  url: string;
  method: string;
  authorization: string;
}

function platform(respond: (url: string) => Response, seen: Seen[] = []): TeamPlatform {
  return {
    sign: async (message) => `signed(${message.length})`,
    sha256: async (body) => `hash(${body.length})`,
    fetch: async (url, init) => {
      seen.push({ url, method: init.method ?? "GET", authorization: (init.headers as Record<string, string>)["authorization"] ?? "" });
      return respond(url);
    },
  };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("invites", () => {
  test("an invite is the terminal's command or the web client's link", () => {
    expect(parseTeamInvite("plural team join tm-7f3k9-xq2m4 --relay wss://relay.example.com")).toEqual({ code: "tm-7f3k9-xq2m4", relay: "wss://relay.example.com" });
    expect(parseTeamInvite("  $ plural team join tm-1 --relay=wss://r.example ")).toEqual({ code: "tm-1", relay: "wss://r.example" });
    expect(parseTeamInvite("https://plural-room.vercel.app/?team=tm-2&relay=wss%3A%2F%2Fr.example")).toEqual({ code: "tm-2", relay: "wss://r.example" });
    expect(parseTeamInvite("wss://host/r_1?join=abc")).toBeNull();
    expect(parseTeamInvite("hello")).toBeNull();
  });

  test("the invite the owner shares names the code and the relay", () => {
    expect(teamJoinCommand(PROFILE, "tm-1")).toBe("plural team join tm-1 --relay wss://relay.example.com");
    const link = teamJoinLink(PROFILE, "tm-1", { origin: "https://plural-room.vercel.app", pathname: "/" });
    expect(link).toBe("https://plural-room.vercel.app/?team=tm-1&relay=wss%3A%2F%2Frelay.example.com");
    expect(parseTeamInvite(link)).toEqual({ code: "tm-1", relay: PROFILE.relay });
  });
});

test("the relay's http address follows its websocket one", () => {
  expect(httpBase("wss://relay.example.com/")).toBe("https://relay.example.com");
  expect(httpBase("ws://127.0.0.1:8787")).toBe("http://127.0.0.1:8787");
  expect(() => httpBase("ftp://x")).toThrow("is not a relay address");
});

describe("certificates", () => {
  const text = (value: unknown) => btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const cert = (iat: string, exp: string) => `${text({ iat, exp })}.sig`;

  test("one is renewed near its end, never right after it was made", () => {
    const month = cert("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z");
    expect(certificateWindow(month)).toEqual({ issued: Date.parse("2026-11-01T00:00:00Z"), expiry: Date.parse("2026-12-01T00:00:00Z") });
    expect(renewalDue(month, Date.parse("2026-11-20T00:00:00Z"))).toBe(false);
    expect(renewalDue(month, Date.parse("2026-11-25T00:00:00Z"))).toBe(true);
    const short = cert("2026-11-01T00:00:00Z", "2026-11-07T00:00:00Z");
    expect(renewalDue(short, Date.parse("2026-11-01T00:00:10Z"))).toBe(false);
    expect(renewalDue(short, Date.parse("2026-11-05T00:00:00Z"))).toBe(true);
    expect(certificateWindow("garbage")).toBeNull();
  });
});

describe("tunnels", () => {
  test("only the tunnels that open for one session are told apart", () => {
    for (const host of ["calm-fox.trycloudflare.com", "a1b2.ngrok-free.app", "x.ngrok.io", "abc.loca.lt:443"]) {
      expect(isTunnelHost(host)).toBe(true);
    }
    for (const host of ["relay.plrl.host", "relay.example.com", "127.0.0.1:8787", "notngrok.io"]) {
      expect(isTunnelHost(host)).toBe(false);
    }
  });

  test("a closed tunnel is named, not shown as a relay answer", async () => {
    const gone = { ...PROFILE, relay: "wss://gone.trycloudflare.com" };
    const dead = platform(() => new Response("<html>gone</html>", { status: 530 }));
    await expect(fetchSessions(gone, dead)).rejects.toThrow(closedTunnel("gone.trycloudflare.com"));
    await expect(createTeamInvite(gone, dead)).rejects.toThrow("is closed");
    await expect(fetchSessions(PROFILE, dead)).rejects.toThrow("the relay answered 530");
  });
});

describe("sessions", () => {
  test("an https page opens only a wss endpoint", () => {
    const entry = { endpoints: [{ kind: "direct", url: "ws://10.0.0.2:7000/r_1" }, { kind: "relay", url: "wss://relay.example.com/r_1" }] } as SessionCard;
    expect(reachable(entry, "https:")).toBe("wss://relay.example.com/r_1");
    expect(reachable(entry, "http:")).toBe("ws://10.0.0.2:7000/r_1");
    expect(reachable({ endpoints: [{ kind: "direct", url: "ws://10.0.0.2:7000/r_1" }] } as SessionCard, "https:")).toBeNull();
  });

  test("right after joining, the busiest session someone else shares opens", () => {
    const make = (owner_id: string, status: SessionCard["status"], updated_at: string, url = `wss://r.example/${owner_id}`) =>
      ({ room: owner_id, owner: owner_id, owner_id, status, updated_at, endpoints: [{ kind: "relay", url }] }) as SessionCard;
    const cards = [
      make("m_idle", "idle", "2026-11-02T10:05:00Z"),
      make("m_me", "running", "2026-11-02T10:06:00Z"),
      make("m_old", "running", "2026-11-02T10:00:00Z"),
      make("m_new", "running", "2026-11-02T10:04:00Z"),
      make("m_plain", "running", "2026-11-02T10:07:00Z", "ws://10.0.0.2/r"),
    ];
    expect(firstSession(cards, "m_me", "https:")?.card.owner_id).toBe("m_new");
    expect(firstSession(cards, "m_me", "http:")?.card.owner_id).toBe("m_plain");
    expect(firstSession([cards[1]!], "m_me", "https:")).toBeNull();
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

describe("the directory calls", () => {
  test("a request is signed with the platform's key over the message and the body's hash", async () => {
    const header = await authorization(PROFILE, platform(() => json({})), "get", "/x", new Uint8Array(), { timestamp: 1700000000, nonce: "abcd" });
    expect(header).toBe(`Plural cert=CERT ts=1700000000 nonce=abcd sig=signed(${"GET\n/x\n1700000000\nabcd\nhash(0)".length})`);
  });

  test("a join proof names the address and the certificate", async () => {
    const proof = await teamProof(PROFILE, platform(() => json({})), "wss://relay.example.com/r_live", "r_live", { timestamp: 1700000000, nonce: "abcd1234" });
    expect(proof).toMatchObject({ certificate: "CERT", url: "wss://relay.example.com/r_live", ts: 1700000000, nonce: "abcd1234" });
  });

  test("the session list is asked with a signed GET", async () => {
    const seen: Seen[] = [];
    const sessions = await fetchSessions(PROFILE, platform(() => json({ sessions: [card("alia", "r_1")] }), seen));
    expect(sessions.map((entry) => entry.owner)).toEqual(["alia"]);
    expect(seen[0]).toMatchObject({ url: "https://relay.example.com/teams/t_1/sessions", method: "GET" });
    expect(seen[0]?.authorization.startsWith("Plural cert=CERT ts=")).toBe(true);
  });

  test("an invite, a renewal and leaving go to their own paths", async () => {
    const seen: Seen[] = [];
    const relay = platform(() => json({ code: "abc123", expires_at: null, certificate: "NEW" }), seen);
    expect((await createTeamInvite(PROFILE, relay)).code).toBe("abc123");
    expect(await renewCertificate(PROFILE, relay)).toBe("NEW");
    await leaveTeamOnRelay(PROFILE, relay);
    expect(seen.map((entry) => `${entry.method} ${entry.url}`)).toEqual([
      "POST https://relay.example.com/teams/t_1/invites",
      "POST https://relay.example.com/teams/t_1/renew",
      "DELETE https://relay.example.com/teams/t_1/members/m_vlad",
    ]);
  });

  test("a refusal carries the relay's reason", async () => {
    await expect(createTeamInvite(PROFILE, platform(() => json({ error: "only the owner can invite" }, 403)))).rejects.toThrow("only the owner");
    await expect(answer(json({}, 500), PROFILE.relay)).rejects.toThrow("the relay answered 500");
  });
});

describe("the watcher", () => {
  test("keeps the last list when the relay is unreachable and says why", async () => {
    let up = true;
    const watcher = new TeamWatcher(PROFILE, async () => {
      if (!up) {
        throw new Error("connection refused");
      }
      return [card("alia", "r_1")];
    });
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

  test("a second refresh does not start another request while one is slow", async () => {
    let calls = 0;
    let release: () => void = () => undefined;
    const watcher = new TeamWatcher(PROFILE, async () => {
      calls += 1;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return [];
    });
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
