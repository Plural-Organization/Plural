import { afterAll, beforeAll, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseLink, SessionClient } from "@plural/client";
import { startLocalHost, type HostHandle } from "../src/host-process";
import { listSessions, resolveSession } from "../src/sessions";

const saved: Record<string, string | undefined> = {};
let workspace = "";

beforeAll(() => {
  const directory = mkdtempSync(join(tmpdir(), "plural-resume-"));
  workspace = realpathSync(directory);
  mkdirSync(join(workspace, "app"));
  workspace = join(workspace, "app");
  for (const [name, value] of Object.entries({
    PLURAL_HOST_CMD: "uv run plural-host",
    PLURAL_DATA_DIR: join(directory, "data"),
    PLURAL_PROVIDER: "fake",
  })) {
    saved[name] = process.env[name];
    process.env[name] = value;
  }
});

afterAll(() => {
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) {
      delete process.env[name];
    } else {
      process.env[name] = value;
    }
  }
});

async function until(check: () => boolean, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!check()) {
    if (Date.now() > deadline) {
      throw new Error("condition not met in time");
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

async function connect(host: HostHandle): Promise<SessionClient> {
  const client = new SessionClient(parseLink(host.hostLink), { name: "vlad", client: { kind: "test", version: "0" } });
  void (async () => {
    try {
      for await (const _event of client.events()) {
        void _event;
      }
    } catch {
      return;
    }
  })();
  await until(() => client.projection.me !== undefined);
  return client;
}

test("a session is found by the folder, by its title and by its start, and resumes in its own room", async () => {
  const first = await startLocalHost(["--workspace", workspace, "--title", "billing work", "--name", "vlad"]);
  const client = await connect(first);
  await client.send({ type: "prompt.submit", text: "hello there", delivery: "now" });
  await until(() => client.projection.state.run === null && client.projection.state.transcript.length >= 2);
  client.close();
  await first.stop();

  const sessions = await listSessions();
  expect(sessions).toHaveLength(1);
  const [info] = sessions;
  expect(info).toMatchObject({ room: first.room, title: "billing work", prompts: 1 });
  expect(realpathSync(info!.workspace as string)).toBe(realpathSync(workspace));
  expect((await listSessions(workspace)).map((entry) => entry.room)).toEqual([first.room]);
  expect(await listSessions(join(workspace, "elsewhere"))).toEqual([]);

  expect(resolveSession({ kind: "continue" }, sessions, workspace).room).toBe(first.room);
  expect(resolveSession({ kind: "id", value: "billing" }, sessions, "/nowhere").room).toBe(first.room);
  expect(resolveSession({ kind: "id", value: first.room.slice(0, 8) }, sessions, "/nowhere").room).toBe(first.room);

  const again = await startLocalHost(["--room", first.room, "--name", "vlad"]);
  expect(again.room).toBe(first.room);
  const back = await connect(again);
  await until(() => back.projection.state.transcript.some((entry) => entry.kind === "prompt" && entry.text === "hello there"));
  expect((await listSessions()).map((entry) => entry.room)).toEqual([first.room]);
  back.close();
  await again.stop();
}, 120_000);
