import { afterEach, describe, expect, test, vi } from "vitest";
import { DaemonError, daemonMessage, daemonStatus, pickFolder, startRoom } from "./daemon";

// The build under test has no accounts address, so the accounts service is reached at a bare path.
const TICKETS = "/tickets";
const DAEMON = "http://127.0.0.1:47831";

afterEach(() => vi.unstubAllGlobals());

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

// Routes the accounts service and the daemon to canned answers and records what the daemon was sent.
function wire(daemon: (path: string, init: RequestInit) => Response) {
  const sent: { path: string; auth: string | null; body: string | null }[] = [];
  let tickets = 0;
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    if (url === TICKETS) {
      tickets += 1;
      return json({ ticket: `ticket-${tickets}`, expires_at: "2026-11-10T00:01:00Z" });
    }
    const headers = new Headers(init.headers);
    sent.push({ path: url.slice(DAEMON.length), auth: headers.get("authorization"), body: typeof init.body === "string" ? init.body : null });
    return daemon(url.slice(DAEMON.length), init);
  });
  return sent;
}

describe("daemonStatus", () => {
  test("says what a daemon reports", async () => {
    wire(() => json({ daemon: true, version: "0.2.22", linked: true }));
    expect(await daemonStatus(DAEMON)).toEqual({ version: "0.2.22", linked: true });
  });
  test("is null when nothing answers or something else does", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("blocked")));
    expect(await daemonStatus(DAEMON)).toBeNull();
    vi.stubGlobal("fetch", async () => json({ hello: "world" }));
    expect(await daemonStatus(DAEMON)).toBeNull();
    vi.stubGlobal("fetch", async () => json({}, 500));
    expect(await daemonStatus(DAEMON)).toBeNull();
  });
});

describe("asking the daemon", () => {
  test("every call carries a ticket of its own", async () => {
    const sent = wire((path) => (path === "/v1/folders/pick" ? json({ folder: "f_1", name: "app" }) : json({ room: "r_1", guest_link: "g", host_link: "h", folder: "app", title: null }, 201)));
    expect(await pickFolder(DAEMON)).toEqual({ folder: "f_1", name: "app" });
    await startRoom("f_1", "  Spike  ", undefined, DAEMON);
    expect(sent.map((call) => call.auth)).toEqual(["Bearer ticket-1", "Bearer ticket-2"]);
    expect(JSON.parse(sent[1]!.body ?? "{}")).toEqual({ folder: "f_1", title: "Spike" });
  });
  test("the agent the person chose goes with the room, and no key with it", async () => {
    const sent = wire(() => json({ room: "r", guest_link: "g", host_link: "h", folder: "x", title: null, agent: "Ollama (local) · qwen3:4b" }, 201));
    const agent = { preset: "ollama", model: "qwen3:4b", baseUrl: "", contextWindow: "", fastModel: "" };
    expect((await startRoom("f_1", "", agent, DAEMON)).agent).toBe("Ollama (local) · qwen3:4b");
    expect(JSON.parse(sent[0]!.body ?? "{}")).toEqual({ folder: "f_1", title: null, agent });
  });
  test("a closed dialog is no folder", async () => {
    wire(() => json({ folder: null }));
    expect(await pickFolder(DAEMON)).toBeNull();
  });
  test("an empty title is sent as none", async () => {
    const sent = wire(() => json({ room: "r", guest_link: "g", host_link: "h", folder: "x", title: null }, 201));
    await startRoom("f_1", "   ", undefined, DAEMON);
    expect(JSON.parse(sent[0]!.body ?? "{}")).toEqual({ folder: "f_1", title: null });
  });
  test("the daemon's refusal becomes an error that keeps its code", async () => {
    wire(() => json({ error: { code: "wrong_account", message: "x", linked_email: "alia@example.com" } }, 403));
    const error = await startRoom("f_1", "", undefined, DAEMON).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(DaemonError);
    expect((error as DaemonError).linkedEmail).toBe("alia@example.com");
  });
  test("a ticket the computer cannot verify is not called an expired sign-in", async () => {
    wire(() => json({ error: { code: "bad_ticket", message: "the ticket is forged", reason: "forged" } }, 401));
    const forged = (await startRoom("f_1", "", undefined, DAEMON).catch((caught: unknown) => caught)) as DaemonError;
    expect(daemonMessage(forged)).toContain("different Plural accounts service");
    expect(daemonMessage(new DaemonError(401, "bad_ticket", "x", null, "expired"))).toBe("Your sign-in expired. Try again.");
  });
  test("an unreachable daemon is an error, not a crash", async () => {
    vi.stubGlobal("fetch", async (url: string) => {
      if (url === TICKETS) {
        return json({ ticket: "t", expires_at: "2026-11-10T00:01:00Z" });
      }
      throw new TypeError("blocked");
    });
    const error = await pickFolder(DAEMON).catch((caught: unknown) => caught);
    expect((error as DaemonError).code).toBe("unreachable");
  });
});

describe("daemonMessage", () => {
  test("names both accounts when they differ", () => {
    const error = new DaemonError(403, "wrong_account", "x", "alia@example.com");
    expect(daemonMessage(error, "bob@example.com")).toBe("Plural on this computer belongs to alia@example.com, and you are signed in as bob@example.com.");
  });
  test("says what to do for the common refusals and passes the rest through", () => {
    expect(daemonMessage(new DaemonError(409, "not_linked", "x"))).toContain("plural login");
    expect(daemonMessage(new DaemonError(409, "host_failed", "no provider configured"))).toBe("no provider configured");
  });
});
