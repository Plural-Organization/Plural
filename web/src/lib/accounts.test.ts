import { afterEach, describe, expect, test, vi } from "vitest";
import { type Account, AccountError, activeMachines, fetchAccount, loginErrorMessage, planLine, signInUrl } from "./accounts";
import { agentPrompt, linkCommand } from "./agentPrompt";

const BASE = "https://accounts.example";

function account(changes: Partial<Account> = {}): Account {
  return { id: "a_1", email: "alia@example.com", name: "Alia", plan: "trial", plan_ends_at: "2026-11-23T00:00:00Z", trial_started: true, machines: [], ...changes };
}

afterEach(() => vi.unstubAllGlobals());

describe("signInUrl", () => {
  test("sends the person back to where they were", () => {
    expect(signInUrl("https://plrl.host/app", BASE)).toBe(`${BASE}/auth/google/start?return=https%3A%2F%2Fplrl.host%2Fapp`);
  });
});

describe("loginErrorMessage", () => {
  test("says nothing when nothing went wrong and something for every failure", () => {
    expect(loginErrorMessage(null)).toBeNull();
    expect(loginErrorMessage("denied")).toContain("cancelled");
    expect(loginErrorMessage("failed")).toContain("verified");
    expect(loginErrorMessage("whatever")).toContain("did not finish");
  });
});

describe("fetchAccount", () => {
  test("reads the account with the session cookie", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(account()), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    expect((await fetchAccount(BASE))?.email).toBe("alia@example.com");
    expect(fetcher).toHaveBeenCalledWith(`${BASE}/me`, expect.objectContaining({ credentials: "include" }));
  });

  test("a signed out visitor is null, not an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "signed_out", message: "sign in first" } }), { status: 401 })));
    expect(await fetchAccount(BASE)).toBeNull();
  });

  test("other failures say what the service said", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "slow_down", message: "too many requests" } }), { status: 429 })));
    await expect(fetchAccount(BASE)).rejects.toMatchObject({ status: 429, code: "slow_down", message: "too many requests" });
  });

  test("an unreachable service is a plain message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));
    await expect(fetchAccount(BASE)).rejects.toBeInstanceOf(AccountError);
  });
});

describe("planLine", () => {
  const now = Date.parse("2026-11-10T00:00:00Z");
  test("counts the days of the trial", () => {
    expect(planLine(account(), now)).toBe("Trial, 13 days left");
    expect(planLine(account({ plan_ends_at: "2026-11-10T20:00:00Z" }), now)).toBe("Trial, 1 day left");
  });
  test("tells apart a trial not started, an ended one and a paid plan", () => {
    expect(planLine(account({ plan: null, trial_started: false }), now)).toContain("first computer");
    expect(planLine(account({ plan: null }), now)).toBe("Trial ended");
    expect(planLine(account({ plan: "paid" }), now)).toBe("Plan active");
  });
});

test("removed computers are not counted", () => {
  const machine = { id: "m_1", created_at: "2026-11-10T00:00:00Z", last_seen_at: null };
  const all = account({ machines: [{ ...machine, revoked: false }, { ...machine, id: "m_2", revoked: true }] });
  expect(activeMachines(all).map((item) => item.id)).toEqual(["m_1"]);
});

describe("agentPrompt", () => {
  const prompt = agentPrompt("K7QF-29XD");
  test("carries the code and the command that uses it", () => {
    expect(prompt).toContain(linkCommand("K7QF-29XD"));
    expect(linkCommand("K7QF-29XD")).toBe("plural login --code K7QF-29XD");
  });
  test("lists every step itself and forbids what it does not list", () => {
    expect(prompt).toContain("install.sh");
    expect(prompt).toContain("without sudo");
    expect(prompt).toContain("Do not read my files");
    expect(prompt).toContain("PLURAL_OK");
    expect(prompt).not.toMatch(/https?:\/\/(?!raw\.githubusercontent\.com\/Plural-Organization)/);
  });
});
