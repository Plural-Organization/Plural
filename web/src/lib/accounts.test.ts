import { afterEach, describe, expect, test, vi } from "vitest";
import { type Account, AccountError, activeMachines, createTicket, decideDevice, fetchAccount, loginErrorMessage, signInUrl } from "./accounts";
import { agentPrompt, linkCommand } from "./agentPrompt";

const BASE = "https://accounts.example";

function account(changes: Partial<Account> = {}): Account {
  return { id: "a_1", email: "alia@example.com", name: "Alia", machines: [], ...changes };
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

describe("device approval", () => {
  test("approving and refusing go to the matching address with the session", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await decideDevice("K7QF-29XD", true);
    await decideDevice("K7QF-29XD", false);
    const urls = fetcher.mock.calls.map((call) => String(call[0]));
    expect(urls[0]).toMatch(/\/device\/K7QF-29XD\/approve$/);
    expect(urls[1]).toMatch(/\/device\/K7QF-29XD\/deny$/);
    expect(fetcher.mock.calls[0]![1]).toMatchObject({ method: "POST", credentials: "include" });
  });

  test("a code that is wrong says so in the service's words", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "unknown_code", message: "this code is wrong, used or expired" } }), { status: 404 })));
    await expect(decideDevice("NOPE", true)).rejects.toMatchObject({ status: 404, message: "this code is wrong, used or expired" });
  });

  test("the way back keeps the code", () => {
    expect(signInUrl("https://plrl.host/app?device=K7QF-29XD", BASE)).toContain(encodeURIComponent("?device=K7QF-29XD"));
  });
});


describe("createTicket", () => {
  test("asks for the daemon's ticket with no body, and a team directory's by name", async () => {
    const sent: RequestInit[] = [];
    vi.stubGlobal("fetch", async (_: string, init: RequestInit) => {
      sent.push(init);
      return new Response(JSON.stringify({ ticket: "t", expires_at: "2099-01-01T00:00:00Z" }), { status: 200 });
    });
    await createTicket();
    await createTicket("teams");
    expect(sent[0]?.body).toBeUndefined();
    expect(JSON.parse(String(sent[1]?.body))).toEqual({ aud: "teams" });
    expect(sent.every((init) => init.credentials === "include")).toBe(true);
  });
});
