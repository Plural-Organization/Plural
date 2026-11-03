import { describe, expect, test } from "vitest";
import { commandName, commandSuggestions, commandsFor, isHostOnly, localCommand, pluginHints, Projection, visibleCommands, type Command, type LocalEffect } from "../src";

const names = (surface: "terminal" | "browser") => commandsFor(surface).map((command) => command.name);

describe("the catalog", () => {
  test("each client has its own commands and the rest in common", () => {
    expect(names("terminal")).toContain("settings");
    expect(names("terminal")).toContain("quit");
    expect(names("terminal")).not.toContain("draw");
    expect(names("browser")).toContain("draw");
    expect(names("browser")).toContain("leave");
    expect(names("browser")).not.toContain("quit");
    for (const shared of ["help", "who", "invite", "access", "kick", "policy", "skills", "mcp", "agents", "usage", "context", "cancel", "copy"]) {
      expect(names("terminal")).toContain(shared);
      expect(names("browser")).toContain(shared);
    }
  });

  test("a command is listed once per client", () => {
    for (const surface of ["terminal", "browser"] as const) {
      expect(new Set(names(surface)).size).toBe(names(surface).length);
    }
  });

  test("host commands are hidden from guests", () => {
    expect(visibleCommands("terminal", "host").map((command) => command.name)).toContain("abort");
    expect(visibleCommands("terminal", "participant").map((command) => command.name)).not.toContain("abort");
  });

  test("suggestions match the typed prefix", () => {
    expect(commandSuggestions("browser", "/in", "host").map((hint) => hint.name)).toEqual(["invite"]);
    expect(commandSuggestions("browser", "/in", "participant")).toEqual([]);
    expect(commandSuggestions("browser", "/cancel 1", "host")).toEqual([]);
    expect(commandSuggestions("browser", "hello", "host")).toEqual([]);
  });

  test("a plugin's host-only flag is respected", () => {
    const plugins = pluginHints([{ name: "deploy", plugin: "ops", description: "ship it", usage: "/deploy", host_only: true }]);
    expect(commandSuggestions("terminal", "/dep", "host", plugins).map((hint) => hint.name)).toEqual(["deploy"]);
    expect(commandSuggestions("terminal", "/dep", "participant", plugins)).toEqual([]);
    expect(isHostOnly("terminal", "/deploy prod", plugins)).toBe(true);
    expect(isHostOnly("terminal", "/mode review")).toBe(true);
    expect(isHostOnly("terminal", "/who")).toBe(false);
    expect(commandName("/mode review")).toBe("mode");
  });
});

function seen(role: "host" | "participant" | "viewer") {
  const projection = new Projection();
  projection.meId = "p_me";
  projection.state = {
    ...projection.state,
    participants: {
      p_me: { id: "p_me", name: "me", role, connected: true },
      p_bek: { id: "p_bek", name: "bek", role: "participant", connected: true },
    } as never,
    queue: [{ prompt_id: "q_1" }] as never,
  };
  return projection;
}

const sent = (effects: LocalEffect[] | null): Command[] => (effects ?? []).flatMap((effect) => (effect.kind === "send" ? [effect.command] : []));
const said = (effects: LocalEffect[] | null): string[] => (effects ?? []).flatMap((effect) => (effect.kind === "notify" ? [`${effect.tone}: ${effect.text}`] : []));

describe("commands that change the session", () => {
  test("other commands are left to the client", () => {
    expect(localCommand("terminal", "/who", seen("host"))).toBeNull();
    expect(localCommand("browser", "/draw", seen("host"))).toBeNull();
  });

  test("an invite is a link, a one-time code, a viewer code, or a change of who may join", () => {
    const host = seen("host");
    expect(sent(localCommand("terminal", "/invite", host))).toEqual([{ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true }]);
    expect(sent(localCommand("terminal", "/invite once", host))).toEqual([{ type: "invite.create", role: "participant", ttl_s: 3600 }]);
    expect(sent(localCommand("terminal", "/invite viewer", host))).toEqual([{ type: "invite.create", role: "viewer", ttl_s: 3600 }]);
    expect(sent(localCommand("terminal", "/invite revoke", host))).toEqual([{ type: "link.revoke" }]);
    expect(sent(localCommand("terminal", "/invite open", host))).toEqual([{ type: "link.set_admission", mode: "open" }]);
    expect(said(localCommand("terminal", "/invite open", host))).toEqual(["accent: the room link lets people in at once"]);
    expect(said(localCommand("terminal", "/invite nope", host))[0]).toContain("usage: /invite");
  });

  test("a queued prompt is cancelled by its number", () => {
    const host = seen("host");
    expect(sent(localCommand("terminal", "/cancel 1", host))).toEqual([{ type: "queue.cancel", prompt_id: "q_1" }]);
    expect(said(localCommand("terminal", "/cancel 9", host))).toEqual(["warn: usage: /cancel <number from the queue>"]);
  });

  test("a viewer asks for access, a guest is told, the host decides", () => {
    expect(sent(localCommand("terminal", "/access please", seen("viewer")))).toEqual([{ type: "access.request", note: "please" }]);
    expect(said(localCommand("terminal", "/access", seen("participant")))).toEqual(["warn: you can already write"]);
    expect(localCommand("terminal", "/access", seen("host"))).toEqual([{ kind: "ui", action: "access-requests" }]);
    expect(sent(localCommand("terminal", "/access allow bek", seen("host")))).toEqual([{ type: "access.decide", participant_id: "p_bek", decision: "allow" }]);
    expect(sent(localCommand("terminal", "/access revoke bek", seen("host")))).toEqual([{ type: "participant.set_role", participant_id: "p_bek", role: "viewer" }]);
    expect(said(localCommand("terminal", "/access allow nobody", seen("host")))[0]).toContain("usage: /access");
  });

  test("kicking names the person who was removed", () => {
    const effects = localCommand("terminal", "/kick bek", seen("host"));
    expect(sent(effects)).toEqual([{ type: "participant.revoke", participant_id: "p_bek" }]);
    expect(said(effects)).toEqual(["dim: bek was removed from the session"]);
    expect(said(localCommand("terminal", "/kick", seen("host")))[0]).toContain("usage: /kick");
  });

  test("a briefing is shared by the host and asked for from the terminal", () => {
    expect(sent(localCommand("terminal", "/brief share ask", seen("host")))).toEqual([{ type: "session.set_briefing_sharing", mode: "ask" }]);
    expect(localCommand("terminal", "/brief", seen("host"))).toEqual([{ kind: "ui", action: "briefings" }]);
    expect(sent(localCommand("terminal", "/brief what changed", seen("participant")))).toEqual([{ type: "briefing.request", focus: "what changed", update: false }]);
    expect(sent(localCommand("terminal", "/brief update", seen("participant")))).toEqual([{ type: "briefing.request", focus: null, update: true }]);
    expect(localCommand("terminal", "/brief give", seen("participant"))).toEqual([{ kind: "ui", action: "brief-give" }]);
    expect(said(localCommand("browser", "/brief", seen("participant")))[0]).toContain("terminal client");
  });
});
