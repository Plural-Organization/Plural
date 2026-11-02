import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import type { SessionState } from "@plural/client";
import { TopBar } from "../src/components/TopBar";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length) open.pop()?.renderer.destroy();
});

async function bar(team: string | null, sharing: boolean): Promise<string> {
  const state = { prompt_mode: "open" } as SessionState;
  const setup = await testRender(<TopBar state={state} update={null} team={team} sharing={sharing} onSettings={() => {}} />, { width: 100, height: 3 });
  open.push(setup);
  await setup.renderOnce();
  return setup.captureCharFrame();
}

test("a shared session shows the team name only", async () => {
  const frame = await bar("Backend", true);
  expect(frame).toContain("◆ Backend");
  expect(frame).not.toContain("private");
});

test("a private session inside a team says so", async () => {
  expect(await bar("Backend", false)).toContain("◆ Backend · this session is private");
});

test("outside a team the bar has no team label", async () => {
  expect(await bar(null, true)).not.toContain("◆");
});
