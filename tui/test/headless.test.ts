import { describe, expect, test } from "bun:test";
import { planAgent, envKey } from "../src/agent";
import { emptyOptions, UsageError } from "../src/options";
import { composePrompt, runPrint } from "../src/print";
import { DEFAULT_SETTINGS, type Settings } from "../src/settings";
import { startupCommands, toolRule } from "../src/startup";
import { FakeSession, HOST } from "./support/fake-session";

const saved: Settings = {
  ...DEFAULT_SETTINGS,
  agent: { preset: "anthropic", model: "claude-opus-5-5", baseUrl: "", contextWindow: "" },
  agentChoices: { openai: { preset: "openai", model: "gpt-saved", baseUrl: "", contextWindow: "" } },
};
const NO_ENV = {};

describe("which model a run uses", () => {
  test("the saved choice and its stored key when nothing is said", () => {
    const plan = planAgent(saved, { anthropic: "sk-saved" }, emptyOptions(), NO_ENV);
    expect(plan.choice).toMatchObject({ preset: "anthropic", model: "claude-opus-5-5" });
    expect([plan.key, plan.problem]).toEqual(["sk-saved", null]);
  });

  test("--model changes only the model of that choice", () => {
    const plan = planAgent(saved, { anthropic: "k" }, { ...emptyOptions(), model: "claude-haiku-4-5" }, NO_ENV);
    expect(plan.choice).toMatchObject({ preset: "anthropic", model: "claude-haiku-4-5" });
  });

  test("--provider picks that provider with what was saved for it, or its first model", () => {
    expect(planAgent(saved, { openai: "k" }, { ...emptyOptions(), provider: "openai" }, NO_ENV).choice).toMatchObject({ preset: "openai", model: "gpt-saved" });
    const fresh = planAgent(saved, { groq: "k" }, { ...emptyOptions(), provider: "groq" }, NO_ENV);
    expect(fresh.choice?.preset).toBe("groq");
    expect(fresh.choice?.model).not.toBe("");
  });

  test("an unknown provider is named in the error", () => {
    expect(() => planAgent(saved, {}, { ...emptyOptions(), provider: "skynet" }, NO_ENV)).toThrow(UsageError);
    expect(() => planAgent(saved, {}, { ...emptyOptions(), provider: "skynet" }, NO_ENV)).toThrow(/--provider takes one of/);
  });

  test("a key missing from the store is taken from the usual environment variable", () => {
    expect(envKey("anthropic", { ANTHROPIC_API_KEY: "sk-env" })).toBe("sk-env");
    expect(envKey("gemini", { GOOGLE_API_KEY: "g" })).toBe("g");
    expect(envKey("ollama", { ANTHROPIC_API_KEY: "x" })).toBe("");
    const plan = planAgent(saved, {}, emptyOptions(), { ANTHROPIC_API_KEY: "sk-env" });
    expect([plan.key, plan.problem]).toEqual(["sk-env", null]);
  });

  test("without any key the problem is reported and left for the caller", () => {
    const plan = planAgent(saved, {}, emptyOptions(), NO_ENV);
    expect(plan.problem).toContain("API key");
  });

  test("the demo agent and the effort go to the host as environment", () => {
    const plan = planAgent(DEFAULT_SETTINGS, {}, { ...emptyOptions(), model: "some-model", effort: "high" }, NO_ENV);
    expect(plan.choice).toBeNull();
    expect(plan.env).toEqual({ PLURAL_MODEL: "some-model", PLURAL_EFFORT: "high" });
  });
});

describe("tools in --allowedTools and --disallowedTools", () => {
  test("a name alone means every use, a pattern in brackets narrows it", () => {
    expect(toolRule("Read")).toEqual({ tool: "read", pattern: "*" });
    expect(toolRule("Bash(git log *)")).toEqual({ tool: "bash", pattern: "git log *" });
    expect(toolRule("Bash(npm run test:*)")).toEqual({ tool: "bash", pattern: "npm run test *" });
    expect(toolRule("MultiEdit")).toEqual({ tool: "multi_edit", pattern: "*" });
    expect(toolRule("WebFetch")).toEqual({ tool: "web_fetch", pattern: "*" });
  });

  test("a tool that does not exist is refused with the list", () => {
    expect(() => toolRule("Teleport")).toThrow(/there is no tool Teleport/);
    expect(() => toolRule("Bash(")).toThrow(UsageError);
  });

  test("the mode comes first, then the permissions and last the denials, because the last matching rule wins", () => {
    const commands = startupCommands({ permissionMode: "accept_edits", allowedTools: ["Bash(git *)"], disallowedTools: ["Bash(git push*)"] });
    expect(commands).toEqual([
      { type: "session.set_permission_mode", mode: "accept_edits" },
      { type: "policy.add", tool: "bash", pattern: "git *", action: "allow" },
      { type: "policy.add", tool: "bash", pattern: "git push*", action: "deny" },
    ]);
    expect(startupCommands({ permissionMode: null, allowedTools: [], disallowedTools: [] })).toEqual([]);
  });
});

describe("the prompt", () => {
  test("piped text goes before the prompt and either may stand alone", () => {
    expect(composePrompt("what is wrong?", "error: boom\n\n")).toBe("error: boom\n\nwhat is wrong?");
    expect(composePrompt(null, "just this\n")).toBe("just this");
    expect(composePrompt("only this", "")).toBe("only this");
    expect(composePrompt("   ", "  \n")).toBe("");
  });
});

class Capture {
  text = "";
  write(text: string): void {
    this.text += text;
  }
}

function welcome(fake: FakeSession): void {
  fake.emit({ type: "session.welcome", room: "r_1", token: "SECRET-TOKEN", participant: HOST, base_policy: [], agent: "demo agent (scripted)" });
}

async function answer(fake: FakeSession, run: (fake: FakeSession) => Promise<void>): Promise<void> {
  welcome(fake);
  const deadline = Date.now() + 2000;
  while (!fake.sent.some((command) => command.type === "prompt.submit")) {
    if (Date.now() > deadline) throw new Error("the prompt was never sent");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  await run(fake);
}

const request = { prompt: "explain", format: "text" as const, commands: [], room: "r_1" };
const REPLY = { type: "message.ended", run_id: "run", message_id: "m1", text: "It is a small tool.", thinking: "" } as const;
const STOP = { type: "run.ended", run_id: "run", reason: "stop", usage: { input_tokens: 10, output_tokens: 5 } } as never;

describe("one question, one answer", () => {
  test("text: the last answer on stdout, the session started with the startup commands first", async () => {
    const fake = new FakeSession();
    const out = new Capture();
    const err = new Capture();
    const done = runPrint(fake, { ...request, commands: [{ type: "session.set_permission_mode", mode: "plan" }] }, out, err);
    await answer(fake, async () => {
      fake.emit({ type: "message.started", run_id: "run", message_id: "m0" } as never);
      fake.emit({ ...REPLY, message_id: "m0", text: "first thought" });
      fake.emit({ type: "message.started", run_id: "run", message_id: "m1" } as never);
      fake.emit(REPLY);
      fake.emit(STOP);
    });
    expect(await done).toBe(0);
    expect(out.text).toBe("It is a small tool.\n");
    expect(err.text).toBe("");
    expect(fake.sent.map((command) => command.type)).toEqual(["session.set_permission_mode", "prompt.submit"]);
    expect(fake.sent.at(-1)).toMatchObject({ text: "explain", delivery: "now" });
  });

  test("json: one result object with the session id, the turns, the usage and the answer", async () => {
    const fake = new FakeSession();
    const out = new Capture();
    const done = runPrint(fake, { ...request, format: "json" }, out, new Capture(), (() => { let now = 1000; return () => (now += 250); })());
    await answer(fake, async () => {
      fake.emit({ type: "message.started", run_id: "run", message_id: "m1" } as never);
      fake.emit(REPLY);
      fake.emit(STOP);
    });
    expect(await done).toBe(0);
    const lines = out.text.trim().split("\n");
    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0] as string)).toMatchObject({
      type: "result",
      subtype: "success",
      is_error: false,
      result: "It is a small tool.",
      session_id: "r_1",
      num_turns: 1,
      usage: { input_tokens: 10, output_tokens: 5 },
      denied: [],
      error: null,
    });
  });

  test("stream-json: every event as a line, then the result, and never the welcome with its token", async () => {
    const fake = new FakeSession();
    const out = new Capture();
    const done = runPrint(fake, { ...request, format: "stream-json" }, out, new Capture());
    await answer(fake, async () => {
      fake.emit({ type: "message.started", run_id: "run", message_id: "m1" } as never);
      fake.emit({ type: "message.delta", message_id: "m1", text: "It is ", thinking: false } as never);
      fake.emit(REPLY);
      fake.emit(STOP);
    });
    await done;
    const lines = out.text.trim().split("\n").map((line) => JSON.parse(line) as { type: string });
    expect(lines.map((line) => line.type)).toEqual(["message.started", "message.delta", "message.ended", "run.ended", "result"]);
    expect(out.text).not.toContain("SECRET-TOKEN");
  });

  test("an action that needs approval is refused, said on stderr and listed", async () => {
    const fake = new FakeSession();
    const out = new Capture();
    const err = new Capture();
    const done = runPrint(fake, { ...request, format: "json" }, out, err);
    await answer(fake, async () => {
      fake.emit({
        type: "approval.requested",
        approval: { id: "ap_1", call: { id: "t1", name: "bash", risk: "exec", subject: "rm -rf build", args: {} }, provenance: { initiator_id: "p_host", initiator_role: "host", origin: "direct" }, timeout_at: "2026-10-28T13:00:00Z", suggested_patterns: [] },
      } as never);
      await new Promise((resolve) => setTimeout(resolve, 30));
      fake.emit(STOP);
    });
    expect(await done).toBe(0);
    expect(fake.sent.find((command) => command.type === "approval.respond")).toMatchObject({ approval_id: "ap_1", decision: "reject" });
    expect(err.text).toContain("denied: bash rm -rf build");
    expect(JSON.parse(out.text.trim()).denied).toEqual(["bash rm -rf build"]);
  });

  test("a run that fails gives exit code 1, the reason and the error", async () => {
    const fake = new FakeSession();
    const out = new Capture();
    const err = new Capture();
    const done = runPrint(fake, { ...request, format: "json" }, out, err);
    await answer(fake, async () => {
      fake.emit({ type: "run.ended", run_id: "run", reason: "error", usage: { input_tokens: 1, output_tokens: 0 }, error: "the key was refused (401)" } as never);
    });
    expect(await done).toBe(1);
    expect(JSON.parse(out.text.trim())).toMatchObject({ subtype: "error", is_error: true, error: "the key was refused (401)" });
    expect(err.text).toContain("run ended: error (the key was refused (401))");
  });

  test("a prompt the host refuses ends the run with the host's words", async () => {
    const fake = new FakeSession();
    const err = new Capture();
    const out = new Capture();
    const done = runPrint(fake, { ...request, format: "json" }, out, err);
    await answer(fake, async () => {
      fake.emit({ type: "error", code: "conflict", message: "the agent is busy" } as never);
      await new Promise((resolve) => setTimeout(resolve, 30));
      fake.close();
    });
    expect(await done).toBe(1);
    expect(err.text).toContain("the agent is busy");
    expect(JSON.parse(out.text.trim())).toMatchObject({ is_error: true, error: "the agent is busy" });
  });

  test("a prompt that the host answers with an error ends the run at once", async () => {
    class Refusing extends FakeSession {
      override async send(command: Parameters<FakeSession["send"]>[0]): Promise<void> {
        if (command.type === "prompt.submit") {
          throw new Error("forbidden: viewer cannot prompt.submit");
        }
        await super.send(command);
      }
    }
    const fake = new Refusing();
    const out = new Capture();
    const err = new Capture();
    const done = runPrint(fake, { ...request, format: "json" }, out, err);
    welcome(fake);
    expect(await done).toBe(1);
    expect(JSON.parse(out.text.trim())).toMatchObject({ is_error: true, error: "forbidden: viewer cannot prompt.submit" });
  });
});
