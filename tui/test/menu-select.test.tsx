import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import { FakeSession, HOST } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

test("clicking and dragging over the menu selects no text", async () => {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "anthropic · claude-opus-5-5" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(<App client={fake} room="r_1" version="0.2.9" guestLink={null} settings={{ ...DEFAULT_SETTINGS, setupSeen: true }} onQuit={() => undefined} />, { width: 130, height: 46 });
  open.push(setup);
  await wait(200);
  setup.mockInput.pressKey("F2");
  await wait(200);
  await setup.renderOnce();
  const lines = setup.captureCharFrame().split("\n");
  const row = lines.findIndex((line) => line.includes("tab next tab"));
  const column = lines[row]!.indexOf("tab next tab");
  await setup.mockMouse.doubleClick(column + 2, row);
  await setup.mockMouse.drag(column, row, column + 8, row);
  await setup.renderOnce();
  // Nothing selected means nothing for copy-on-select to put on the clipboard.
  expect(setup.renderer.getSelection()?.getSelectedText() ?? "").toBe("");
});
