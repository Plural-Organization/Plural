import { describe, expect, test } from "bun:test";
import { buildSpaces, neighbour, OWN, type Visit } from "../src/spaces";
import type { SessionCard, TeamView } from "../src/team";

const card = (owner: string, status: SessionCard["status"] = "idle", branch: string | null = "main", viewers = 0): SessionCard => ({
  room: `r_${owner}`,
  repo: "plural",
  branch,
  title: null,
  status,
  viewers,
  endpoints: [{ kind: "relay", url: `wss://r/r_${owner}` }],
  owner,
  owner_id: `m_${owner}`,
  updated_at: "2026-10-29T12:00:00Z",
});

const team = (...sessions: SessionCard[]): TeamView => ({ name: "Backend", me: "m_vlad", sessions, error: null });

describe("the list of spaces", () => {
  test("starts with my own session and then the team's, each with where and what", () => {
    const rows = buildSpaces({ home: "api", team: team(card("alia", "running", "feat/x", 2), card("bek", "waiting")), visits: [], active: OWN, summaries: {} });
    expect(rows.map((row) => [row.id, row.title, row.detail, row.status, row.viewers, row.active])).toEqual([
      [OWN, "you", "api", "idle", 0, true],
      ["r_alia", "alia", "plural · feat/x", "running", 2, false],
      ["r_bek", "bek", "plural · main", "waiting", 0, false],
    ]);
  });

  test("my own card names the repository and branch when I share it", () => {
    const rows = buildSpaces({ home: "api", team: team(card("vlad", "idle", "fix/login", 1), card("alia")), visits: [], active: OWN, summaries: {} });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ detail: "plural · fix/login", viewers: 1, mine: true });
  });

  test("what an open session says about itself wins over the last poll", () => {
    const rows = buildSpaces({
      home: "api",
      team: team(card("alia", "idle")),
      visits: [],
      active: "r_alia",
      summaries: { [OWN]: { phase: "waiting" }, r_alia: { phase: "running" } },
    });
    expect(rows.map((row) => [row.id, row.status, row.active])).toEqual([
      [OWN, "waiting", false],
      ["r_alia", "running", true],
    ]);
  });

  test("a session I opened stays listed, marked offline, when its card is gone", () => {
    const visits: Visit[] = [{ id: "r_alia", card: card("alia") }];
    const rows = buildSpaces({ home: "api", team: team(), visits, active: "r_alia", summaries: {} });
    expect(rows[1]).toMatchObject({ id: "r_alia", offline: true, active: true });
  });

  test("works with no team at all", () => {
    expect(buildSpaces({ home: "api", team: null, visits: [], active: OWN, summaries: {} })).toHaveLength(1);
  });

  test("moving to the next or previous space wraps around", () => {
    const rows = buildSpaces({ home: "api", team: team(card("alia"), card("bek")), visits: [], active: OWN, summaries: {} });
    expect(neighbour(rows, OWN, 1)).toBe("r_alia");
    expect(neighbour(rows, "r_bek", 1)).toBe(OWN);
    expect(neighbour(rows, OWN, -1)).toBe("r_bek");
    expect(neighbour(rows, "gone", 1)).toBe("r_alia");
  });
});
