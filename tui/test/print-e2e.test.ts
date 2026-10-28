import { beforeAll, describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const CLI = resolve(import.meta.dir, "../src/cli.tsx");
const PROJECT = resolve(import.meta.dir, "../..");
let workspace = "";
let env: Record<string, string> = {};

beforeAll(() => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "plural-print-")));
  workspace = join(root, "app");
  mkdirSync(workspace);
  writeFileSync(join(workspace, "notes.txt"), "alpha\nbeta\n");
  env = {
    ...(process.env as Record<string, string>),
    PLURAL_DATA_DIR: join(root, "data"),
    PLURAL_HOST_CMD: `uv run --project ${PROJECT} plural-host`,
    PLURAL_PROVIDER: "fake",
  };
  delete env["ANTHROPIC_API_KEY"];
  delete env["OPENAI_API_KEY"];
});

async function plural(args: string[], input?: string): Promise<{ code: number; out: string; err: string }> {
  const child = Bun.spawn([process.execPath, CLI, ...args], { cwd: workspace, env, stdin: input === undefined ? "ignore" : new TextEncoder().encode(input), stdout: "pipe", stderr: "pipe" });
  const [out, err, code] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited]);
  return { code, out, err };
}

describe("plural -p against a real host", () => {
  test("answers once on stdout and exits", async () => {
    const run = await plural(["-p", "what is in this folder?"]);
    expect(run.code).toBe(0);
    expect(run.out).toContain("notes.txt");
    expect(run.err).toBe("");
  }, 60_000);

  test("json names the session, which can then be resumed to ask again", async () => {
    const first = await plural(["-p", "list it", "--output-format", "json"]);
    expect(first.code).toBe(0);
    const result = JSON.parse(first.out.trim());
    expect(result).toMatchObject({ type: "result", subtype: "success", is_error: false, denied: [] });
    expect(result.session_id).toMatch(/^r_/);
    expect(result.num_turns).toBeGreaterThanOrEqual(1);

    const again = await plural(["-r", result.session_id, "-p", "and again", "--output-format", "json"]);
    expect(again.code).toBe(0);
    expect(JSON.parse(again.out.trim()).session_id).toBe(result.session_id);

    const sessions = JSON.parse((await plural(["sessions", "--json"])).out) as { room: string; prompts: number; title: string }[];
    const found = sessions.find((entry) => entry.room === result.session_id);
    expect(found?.prompts).toBe(2);
    expect(found?.title).toBe("list it");
  }, 120_000);

  test("text piped in becomes the prompt, or goes before it", async () => {
    const run = await plural(["-p", "--output-format", "json"], "summarize this log\n");
    expect(run.code).toBe(0);
    const id = JSON.parse(run.out.trim()).session_id as string;
    const sessions = JSON.parse((await plural(["sessions", "--json"])).out) as { room: string; title: string }[];
    expect(sessions.find((entry) => entry.room === id)?.title).toBe("summarize this log");

    const both = await plural(["-p", "what failed?", "--output-format", "json"], "error: boom\n");
    const bothId = JSON.parse(both.out.trim()).session_id as string;
    const after = JSON.parse((await plural(["sessions", "--json"])).out) as { room: string; title: string }[];
    expect(after.find((entry) => entry.room === bothId)?.title).toBe("error: boom");
  }, 120_000);

  test("a command that needs approval is refused unless it is allowed", async () => {
    const refused = await plural(["-p", "$ echo hello-from-tool", "--output-format", "json"]);
    expect(refused.code).toBe(0);
    expect(refused.err).toContain("denied: bash echo hello-from-tool");
    expect(JSON.parse(refused.out.trim()).denied).toEqual(["bash echo hello-from-tool"]);
    expect(refused.out).not.toContain("hello-from-tool\\n");

    const allowed = await plural(["-p", "$ echo hello-from-tool", "--allowedTools", "Bash(echo *)"]);
    expect(allowed.code).toBe(0);
    expect(allowed.err).toBe("");
    expect(allowed.out).toContain("hello-from-tool");
  }, 120_000);

  test("a denial wins over a permission that also fits", async () => {
    const run = await plural(["-p", "$ echo secret-thing", "--allowedTools", "Bash(echo *)", "--disallowedTools", "Bash(echo secret*)"]);
    expect(run.code).toBe(0);
    expect(run.out).toContain("Denied");
    expect(run.out).not.toContain("secret-thing\n");
  }, 60_000);

  test("stream-json is one event per line and ends with the result", async () => {
    const run = await plural(["-p", "list it", "--output-format", "stream-json"]);
    expect(run.code).toBe(0);
    const lines = run.out.trim().split("\n").map((line) => JSON.parse(line) as { type: string });
    expect(lines.at(-1)?.type).toBe("result");
    expect(lines.some((line) => line.type === "run.started")).toBe(true);
    expect(run.out).not.toContain('"token"');
  }, 60_000);

  test("mistakes are explained before anything starts", async () => {
    expect((await plural(["-p"])).err).toContain("-p needs a prompt");
    expect((await plural(["-p", "x", "--tunnel", "ngrok"])).err).toContain("--tunnel shares a session");
    expect((await plural(["-p", "x", "--provider", "skynet"])).err).toContain("--provider takes one of");
    expect((await plural(["-p", "x", "--allowedTools", "Teleport"])).err).toContain("there is no tool Teleport");
    expect((await plural(["-p", "x", "--permission-mode", "yolo"])).err).toContain("--permission-mode takes");
    expect((await plural(["-p", "x", "--provider", "anthropic"])).err).toContain("API key");
  }, 120_000);
});
