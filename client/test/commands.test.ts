import { describe, expect, test } from "vitest";
import { isHostOnly, listedCommands, localCommand, parseSlash, SlashError, suggestCommands, visibleCommands } from "../src";

const names = (surface: "tui" | "web") => listedCommands(surface).map((hint) => hint.name);

describe("the command registry", () => {
  test("each client is offered the commands it had before the list was shared, in one order", () => {
    expect(names("web")).toEqual([
      "help", "who", "draw", "team", "invite", "import", "brief", "access", "preview", "kick", "mode", "replies", "danger", "policy", "skills",
      "mcp", "usage", "context", "trace", "plugins", "compact", "abort", "cancel", "copy", "leave",
    ]);
    expect(names("tui")).toEqual([
      "help", "who", "team", "invite", "import", "ask", "access", "preview", "kick", "mode", "replies", "danger", "policy", "skills", "mcp",
      "agents", "usage", "context", "trace", "plugins", "fork", "resume", "compact", "abort", "cancel", "settings", "copy", "quit",
    ]);
  });

  test("a command is named once, and has a usage that starts with its name", () => {
    for (const surface of ["tui", "web"] as const) {
      const seen = names(surface);
      expect(new Set(seen).size).toBe(seen.length);
      for (const hint of listedCommands(surface)) {
        expect(hint.usage.startsWith(`/${hint.name}`)).toBe(true);
        expect(hint.description).not.toBe("");
      }
    }
  });

  test("a surface can word a command its own way", () => {
    const invite = (surface: "tui" | "web") => listedCommands(surface).find((hint) => hint.name === "invite")?.description;
    expect(invite("tui")).toContain("copy the room link");
    expect(invite("web")).toContain("show the room link");
  });

  test("a command that works on a surface but is not offered there still works", () => {
    expect(names("tui")).not.toContain("brief");
    expect(localCommand("tui", "brief")?.name).toBe("brief");
    expect(names("web")).not.toContain("ask");
    expect(localCommand("web", "ask")?.name).toBe("ask");
    expect(names("web")).not.toContain("agents");
    expect(parseSlash("/agents")).toEqual({ type: "show.agents" });
  });

  test("a local command is one only where it works", () => {
    expect(localCommand("web", "draw")?.name).toBe("draw");
    expect(localCommand("tui", "draw")).toBeUndefined();
    expect(localCommand("tui", "fork")?.name).toBe("fork");
    expect(localCommand("web", "fork")).toBeUndefined();
    // Parsed and chat commands are not local: the shared parser or the chat parser takes them.
    expect(localCommand("web", "mode")).toBeUndefined();
    expect(localCommand("web", "team")).toBeUndefined();
    expect(localCommand("web", "nope")).toBeUndefined();
  });

  test("a local command does not parse, so a client that does not carry it out says it is unknown", () => {
    expect(() => parseSlash("/draw")).toThrow(SlashError);
    expect(() => parseSlash("/draw")).toThrow(/unknown command \/draw/);
    expect(() => parseSlash("/nope")).toThrow(/unknown command \/nope/);
  });

  test("every parsed command refuses nonsense with a SlashError, not a crash", () => {
    for (const name of ["mode", "replies", "danger", "policy", "skills", "mcp", "agents", "plugins"]) {
      const result = (() => {
        try {
          return parseSlash(`/${name} ???`);
        } catch (error) {
          return error;
        }
      })();
      expect(result instanceof SlashError || (result !== null && typeof result === "object" && "type" in result)).toBe(true);
    }
  });

  test("a plugin command runs through the host, a built-in one cannot be shadowed", () => {
    expect(parseSlash("/deploy prod", new Set(["deploy"]))).toEqual({ type: "command.run", name: "deploy", args: "prod" });
    expect(parseSlash("/mode review", new Set(["mode"]))).toEqual({ type: "session.set_prompt_mode", mode: "review" });
  });

  test("host-only commands are hidden from everyone else and refused by name", () => {
    expect(suggestCommands("web", "/in", "host").map((hint) => hint.name)).toEqual(["invite"]);
    expect(suggestCommands("web", "/in", "participant")).toEqual([]);
    expect(suggestCommands("web", "/cancel 1", "host")).toEqual([]);
    expect(suggestCommands("web", "hello", "host")).toEqual([]);
    expect(visibleCommands("tui", "participant").some((hint) => hint.hostOnly)).toBe(false);
    expect(isHostOnly("web", "/mode review")).toBe(true);
    expect(isHostOnly("web", "/who")).toBe(false);
    expect(isHostOnly("tui", "/fork x")).toBe(true);
    expect(isHostOnly("web", "/deploy", [{ name: "deploy", usage: "/deploy", description: "", hostOnly: true }])).toBe(true);
  });
});
