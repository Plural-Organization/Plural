import { describe, expect, test } from "bun:test";
import { parseArgs, permissionModeOf, UsageError, type SessionOptions } from "../src/options";

function session(...argv: string[]): SessionOptions {
  const parsed = parseArgs(argv);
  if (parsed.kind !== "session") {
    throw new Error(`expected a session, got ${parsed.kind}`);
  }
  return parsed.options;
}

describe("commands", () => {
  test("version, help and the self test", () => {
    expect(parseArgs(["-v"]).kind).toBe("version");
    expect(parseArgs(["--version"]).kind).toBe("version");
    expect(parseArgs(["-h"]).kind).toBe("help");
    expect(parseArgs(["--selftest"]).kind).toBe("selftest");
  });

  test("the host's own commands go straight through", () => {
    for (const name of ["relay", "doctor", "export", "sessions", "rm"]) {
      expect(parseArgs([name, "--json"])).toEqual({ kind: "passthrough", args: [name, "--json"] });
    }
  });

  test("join takes a link and a display name", () => {
    expect(parseArgs(["join", "wss://r.example.com/r_1?invite=a", "--name", "alia"])).toEqual({
      kind: "join",
      link: "wss://r.example.com/r_1?invite=a",
      displayName: "alia",
    });
    expect(parseArgs(["join"])).toEqual({ kind: "join", link: null, displayName: null });
    expect(() => parseArgs(["join", "a", "b"])).toThrow(UsageError);
    expect(() => parseArgs(["join", "a", "--wat"])).toThrow(/unknown option --wat/);
  });
});

describe("a session", () => {
  test("no arguments is a new session here", () => {
    const options = session();
    expect(options.hostArgs).toEqual([]);
    expect(options.resume).toBeNull();
    expect(options.print).toBe(false);
    expect(options.prompt).toBeNull();
  });

  test("the word host in front is accepted", () => {
    expect(session("host", "--workspace", "/w").hostArgs).toEqual(["--workspace", "/w"]);
  });

  test("host options are kept for the host in the order given", () => {
    const options = session("--workspace", "/w", "--prompts", "review", "--port", "7001", "--relay", "wss://r.example.com", "--public-url", "wss://p.example.com", "--bind", "0.0.0.0", "--room", "r_1");
    expect(options.hostArgs).toEqual(["--workspace", "/w", "--prompts", "review", "--port", "7001", "--relay", "wss://r.example.com", "--public-url", "wss://p.example.com", "--bind", "0.0.0.0", "--room", "r_1"]);
  });

  test("--flag=value works like --flag value", () => {
    expect(session("--workspace=/w", "--model=gpt-x").hostArgs).toEqual(["--workspace", "/w"]);
    expect(session("--model=gpt-x").model).toBe("gpt-x");
  });

  test("a title can be given as --title or -n, the display name stays --name", () => {
    expect(session("--title", "refactor auth").hostArgs).toEqual(["--title", "refactor auth"]);
    expect(session("-n", "refactor auth").hostArgs).toEqual(["--title", "refactor auth"]);
    const options = session("--name", "vlad");
    expect(options.displayName).toBe("vlad");
    expect(options.hostArgs).toEqual([]);
  });

  test("a tunnel is kept as typed so it can be named in an error", () => {
    expect(session("--tunnel", "cloudflare").tunnel).toBe("cloudflare");
  });

  test("a value must follow the option", () => {
    expect(() => session("--workspace")).toThrow(/--workspace needs a value/);
    expect(() => session("--model", "--print")).toThrow(/--model needs a value/);
  });

  test("an unknown option is refused with a pointer to the help", () => {
    expect(() => session("--tunel", "ngrok")).toThrow(/unknown option --tunel/);
    expect(() => session("-z")).toThrow(UsageError);
  });
});

describe("resuming", () => {
  test("-r alone opens the chooser, -r with a word names the session, -c continues", () => {
    expect(session("-r").resume).toEqual({ kind: "pick" });
    expect(session("--resume").resume).toEqual({ kind: "pick" });
    expect(session("-r", "refactor").resume).toEqual({ kind: "id", value: "refactor" });
    expect(session("--resume", "r_01ABC").resume).toEqual({ kind: "id", value: "r_01ABC" });
    expect(session("-c").resume).toEqual({ kind: "continue" });
    expect(session("--continue").resume).toEqual({ kind: "continue" });
  });

  test("-r followed by another option still opens the chooser", () => {
    const options = session("-r", "--workspace", "/w");
    expect(options.resume).toEqual({ kind: "pick" });
    expect(options.hostArgs).toEqual(["--workspace", "/w"]);
  });

  test("resume and --room together are a mistake", () => {
    expect(() => session("-r", "x", "--room", "r_1")).toThrow(/either --resume or --room/);
    expect(() => session("-c", "--room", "r_1")).toThrow(UsageError);
  });
});

describe("a prompt and printing", () => {
  test("words that are no option make the first prompt", () => {
    expect(session("fix", "the", "failing test").prompt).toBe("fix the failing test");
    expect(session("-r", "--tunnel", "ngrok", "continue the work").prompt).toBe("continue the work");
  });

  test("-p prints once and says what format", () => {
    const options = session("-p", "explain this repo", "--output-format", "json");
    expect(options.print).toBe(true);
    expect(options.prompt).toBe("explain this repo");
    expect(options.outputFormat).toBe("json");
    expect(() => session("-p", "x", "--output-format", "xml")).toThrow(/--output-format takes/);
  });

  test("the model, the effort and the permission mode are checked", () => {
    const options = session("--model", "claude-opus-5-5", "--provider", "anthropic", "--effort", "high", "--permission-mode", "acceptEdits");
    expect([options.model, options.provider, options.effort, options.permissionMode]).toEqual(["claude-opus-5-5", "anthropic", "high", "accept_edits"]);
    expect(() => session("--effort", "huge")).toThrow(/--effort takes/);
    expect(() => session("--permission-mode", "yolo")).toThrow(/--permission-mode takes/);
    expect(permissionModeOf("PLAN")).toBe("plan");
    expect(permissionModeOf("accept-edits")).toBe("accept_edits");
  });

  test("tool lists split on commas and spaces but keep the parentheses whole", () => {
    const options = session("--allowedTools", "Bash(git log *),Read Edit", "--disallowed-tools", "Bash(rm -rf *)", "--allowed-tools", "Grep");
    expect(options.allowedTools).toEqual(["Bash(git log *)", "Read", "Edit", "Grep"]);
    expect(options.disallowedTools).toEqual(["Bash(rm -rf *)"]);
  });
});
