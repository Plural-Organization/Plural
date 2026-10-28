import { describe, expect, test } from "bun:test";
import { mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { forgetJoined, loadJoined, rejoinLink, rememberJoined } from "../src/joined";
import { UsageError } from "../src/options";
import { ago, inFolder, resolveSession, type SessionInfo } from "../src/sessions";

function entry(room: string, title: string, workspace: string | null, updated = "2026-10-28T12:00:00Z"): SessionInfo {
  return { room, title, workspace, host_name: "vlad", created_at: updated, updated_at: updated, prompts: 1, people: 1 };
}

const SESSIONS = [
  entry("r_01NEWEST", "fix the login bug", "/work/app", "2026-10-28T13:00:00Z"),
  entry("r_01MIDDLE", "refactor auth", "/work/app", "2026-10-28T12:00:00Z"),
  entry("r_02OTHER0", "refactor billing", "/work/shop", "2026-10-27T12:00:00Z"),
  entry("r_03LOOSE0", "(no prompt yet)", null),
];

describe("continuing", () => {
  test("takes the newest session of this folder", () => {
    expect(resolveSession({ kind: "continue" }, SESSIONS, "/work/app").room).toBe("r_01NEWEST");
    expect(resolveSession({ kind: "continue" }, SESSIONS, "/work/shop").room).toBe("r_02OTHER0");
  });

  test("says so when the folder has none", () => {
    expect(() => resolveSession({ kind: "continue" }, SESSIONS, "/work/none")).toThrow(/no session in this folder/);
  });

  test("the folders of the sessions are compared", () => {
    expect(inFolder(SESSIONS, "/work/app").map((item) => item.room)).toEqual(["r_01NEWEST", "r_01MIDDLE"]);
  });
});

describe("naming a session", () => {
  const find = (value: string) => resolveSession({ kind: "id", value }, SESSIONS, "/work/app");

  test("by its whole id, by the start of it, or without the r_", () => {
    expect(find("r_02OTHER0").title).toBe("refactor billing");
    expect(find("r_03LO").room).toBe("r_03LOOSE0");
    expect(find("03LO").room).toBe("r_03LOOSE0");
  });

  test("by its title, whole or a piece of it", () => {
    expect(find("Refactor Auth").room).toBe("r_01MIDDLE");
    expect(find("login").room).toBe("r_01NEWEST");
  });

  test("a word that fits two sessions asks which one", () => {
    expect(() => find("refactor")).toThrow(/matches 2 sessions/);
    expect(() => find("r_0")).toThrow(/r_01NEWEST/);
  });

  test("a word that fits none says so", () => {
    expect(() => find("zzz")).toThrow(UsageError);
    expect(() => find("zzz")).toThrow(/plural -r lists/);
  });
});

describe("time", () => {
  const now = new Date("2026-10-28T13:00:00Z");
  test("is said the short way", () => {
    expect(ago("2026-10-28T12:59:30Z", now)).toBe("30s ago");
    expect(ago("2026-10-28T12:15:00Z", now)).toBe("45m ago");
    expect(ago("2026-10-28T08:00:00Z", now)).toBe("5h ago");
    expect(ago("2026-10-25T13:00:00Z", now)).toBe("3d ago");
  });
});

describe("rooms I joined", () => {
  const file = () => join(mkdtempSync(join(tmpdir(), "plural-joined-")), "joined.json");

  test("are remembered newest first, once each, and a missing file is an empty list", () => {
    const path = file();
    expect(loadJoined(path)).toEqual([]);
    rememberJoined({ room: "r_a", url: "wss://r.example.com/r_a", token: "t1", name: "alia" }, path, new Date("2026-10-28T10:00:00Z"));
    rememberJoined({ room: "r_b", url: "wss://r.example.com/r_b", token: "t2", name: "alia" }, path, new Date("2026-10-28T11:00:00Z"));
    rememberJoined({ room: "r_a", url: "wss://r.example.com/r_a", token: "t3", name: "alia" }, path, new Date("2026-10-28T12:00:00Z"));
    expect(loadJoined(path).map((room) => [room.room, room.token])).toEqual([["r_a", "t3"], ["r_b", "t2"]]);
  });

  test("keep the token only for the owner", () => {
    const path = file();
    rememberJoined({ room: "r_a", url: "wss://r.example.com/r_a", token: "secret", name: "alia" }, path);
    expect(statSync(path).mode & 0o777).toBe(0o600);
  });

  test("can be forgotten and give back a link with the token", () => {
    const path = file();
    rememberJoined({ room: "r_a", url: "wss://r.example.com/r_a", token: "t1", name: "alia" }, path);
    const [room] = loadJoined(path);
    expect(rejoinLink(room!)).toBe("wss://r.example.com/r_a?token=t1");
    forgetJoined("r_a", path);
    expect(loadJoined(path)).toEqual([]);
  });

  test("a broken file is ignored and no more than twenty are kept", () => {
    const path = file();
    rememberJoined({ room: "r_0", url: "u", token: "t", name: "n" }, path);
    for (let index = 1; index < 25; index += 1) {
      rememberJoined({ room: `r_${index}`, url: "u", token: "t", name: "n" }, path);
    }
    expect(loadJoined(path)).toHaveLength(20);
    expect(loadJoined(path)[0]?.room).toBe("r_24");
  });
});
