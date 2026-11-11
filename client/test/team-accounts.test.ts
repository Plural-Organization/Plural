import { describe, expect, test } from "vitest";
import {
  accountProofMessage,
  createTeamOnRelay,
  fetchMembers,
  handOverTeam,
  joinTeamOnRelay,
  keyProofMessage,
  myTeamsOnRelay,
  normalizeTeamCode,
  removeMemberOnRelay,
  type TeamGrant,
  type TeamPlatform,
  type TeamProfile,
} from "../src";

interface Sent {
  url: string;
  method: string;
  body: unknown;
  authorization: string | null;
}

function relay(respond: (url: string) => unknown, sent: Sent[] = []): TeamPlatform {
  return {
    sign: async (message) => `signed:${message}`,
    sha256: async (body) => `hash(${body.length})`,
    fetch: async (url, init) => {
      const headers = (init.headers ?? {}) as Record<string, string>;
      const raw = init.body;
      const text = raw === undefined ? null : typeof raw === "string" ? raw : new TextDecoder().decode(raw as Uint8Array);
      sent.push({ url, method: init.method ?? "GET", body: text === null ? null : JSON.parse(text), authorization: headers["authorization"] ?? null });
      return new Response(JSON.stringify(respond(url)), { status: 200, headers: { "content-type": "application/json" } });
    },
  };
}

const grant = (team: string, role: "owner" | "member" = "member"): TeamGrant => ({
  team_id: team,
  team_name: team.toUpperCase(),
  team_key: "TEAMKEY",
  certificate: `cert-${team}`,
  member: { id: "m_vlad", name: "vlad", key: "K", role, joined_at: "2026-11-11T12:00:00Z" },
  invite: role === "owner" ? "tm-abcde-12345" : null,
});

const PROFILE: TeamProfile = {
  relay: "wss://relay.example.com",
  team_id: "t_1",
  team_name: "Backend",
  team_key: "TEAMKEY",
  certificate: "CERT",
  member: { id: "m_vlad", name: "vlad", role: "owner" },
};

test("an invite code signs the way the relay compares it", () => {
  // relay/directory.py normalize_code gives the same for these (tests/unit/test_team_accounts.py).
  expect(normalizeTeamCode("TM-ABcde-12345")).toBe("abcde12345");
  expect(normalizeTeamCode("abcde 12345")).toBe("abcde12345");
  expect(keyProofMessage("tm-abcde-12345")).toBe("plural-team-key:abcde12345");
  expect(accountProofMessage(1700000000, "n-1")).toBe("plural-teams:1700000000:n-1");
});

describe("an account on the relay", () => {
  test("creates a team with its proof and keeps the invite to share", async () => {
    const sent: Sent[] = [];
    const made = await createTeamOnRelay("wss://relay.example.com", relay(() => grant("t_1", "owner"), sent), {
      name: "Backend",
      memberName: "vlad",
      key: "K",
      proof: { ticket: "T" },
    });
    expect(sent[0]).toMatchObject({ url: "https://relay.example.com/teams", method: "POST", body: { name: "Backend", member_name: "vlad", key: "K", proof: { ticket: "T" } } });
    expect(made.invite).toBe("tm-abcde-12345");
    expect(made.profile).toEqual({ relay: "wss://relay.example.com", team_id: "t_1", team_name: "T_1", team_key: "TEAMKEY", certificate: "cert-t_1", member: { id: "m_vlad", name: "vlad", role: "owner" } });
  });

  test("joins with the code, and signs it with the device key only when claiming", async () => {
    const sent: Sent[] = [];
    const platform = relay(() => grant("t_2"), sent);
    await joinTeamOnRelay("wss://relay.example.com", platform, { code: "tm-abcde-12345", name: "vlad", key: "K", proof: { ticket: "T" } });
    await joinTeamOnRelay("wss://relay.example.com", platform, { code: "tm-abcde-12345", name: "vlad", key: "K", proof: { ticket: "T" }, claim: true });
    await joinTeamOnRelay("wss://relay.example.com", platform, { code: "tm-abcde-12345", name: "vlad", key: "K", claim: true });
    expect(sent.map((call) => (call.body as { key_proof?: string }).key_proof ?? null)).toEqual([null, "signed:plural-team-key:abcde12345", null]);
    expect((sent[2]!.body as Record<string, unknown>)["proof"]).toBeUndefined();
  });

  test("gets every team of the account for this device", async () => {
    const sent: Sent[] = [];
    const teams = await myTeamsOnRelay("wss://relay.example.com", relay(() => ({ teams: [grant("t_1", "owner"), grant("t_2")] }), sent), "K", { ticket: "T" });
    expect(sent[0]).toMatchObject({ url: "https://relay.example.com/teams/mine", body: { key: "K", proof: { ticket: "T" } } });
    expect(teams.map((team) => [team.team_id, team.member.role])).toEqual([
      ["t_1", "owner"],
      ["t_2", "member"],
    ]);
  });
});

describe("a member manages the team with signed requests", () => {
  test("lists members, removes one and hands the team over", async () => {
    const sent: Sent[] = [];
    const platform = relay((url) => (url.endsWith("/members") ? { members: [grant("t_1").member] } : grant("t_1").member), sent);
    expect((await fetchMembers(PROFILE, platform)).map((member) => member.name)).toEqual(["vlad"]);
    await removeMemberOnRelay(PROFILE, platform, "m_alia");
    await handOverTeam(PROFILE, platform, "alia");
    expect(sent.map((call) => `${call.method} ${new URL(call.url).pathname}`)).toEqual([
      "GET /teams/t_1/members",
      "DELETE /teams/t_1/members/m_alia",
      "POST /teams/t_1/owner",
    ]);
    expect(sent[2]!.body).toEqual({ member: "alia" });
    // The body is part of what the device signs, so the relay can tell it was not changed.
    expect(sent[2]!.authorization).toContain("sig=signed:POST\n/teams/t_1/owner");
    expect(sent.every((call) => call.authorization?.startsWith("Plural cert=CERT"))).toBe(true);
  });
});
