import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { expandPastes, pasteLabel, shouldCollapse } from "../src/lib/paste";
import { HOST, FakeSession } from "./support/fake-session";

const { App } = await import("../src/App");

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

async function until(setup: Setup, check: () => boolean, timeout = 3000): Promise<void> {
  const deadline = Date.now() + timeout;
  while (!check()) {
    if (Date.now() > deadline) {
      throw new Error(`timed out in:\n${setup.captureCharFrame()}`);
    }
    await setup.renderOnce();
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

async function mount(): Promise<{ fake: FakeSession; setup: Setup }> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "demo" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.0" guestLink={null} onQuit={() => undefined} />,
    { width: 120, height: 36 },
  );
  open.push(setup);
  await until(setup, () => setup.captureCharFrame().includes("Message the agent"));
  return { fake, setup };
}

describe("the paste helpers", () => {
  test("only a long paste is collapsed", () => {
    expect(shouldCollapse("one line")).toBe(false);
    expect(shouldCollapse("a\nb\nc")).toBe(false);
    expect(shouldCollapse("1\n2\n3\n4\n5\n6")).toBe(true);
    expect(shouldCollapse("x".repeat(801))).toBe(true);
  });

  test("the label says how much was pasted", () => {
    expect(pasteLabel(1, "1\n2\n3\n4\n5\n6")).toBe("[Pasted text #1 +6 lines]");
    expect(pasteLabel(2, "x".repeat(900))).toBe("[Pasted text #2 900 chars]");
  });

  test("labels expand back, a deleted one sends nothing", () => {
    const pastes = new Map([["[Pasted text #1 +2 lines]", "a\nb"], ["[Pasted text #2 +2 lines]", "c\nd"]]);
    expect(expandPastes("look: [Pasted text #1 +2 lines] ok", pastes)).toBe("look: a\nb ok");
  });
});

test("a long paste shows as a label and is sent in full", async () => {
  const { fake, setup } = await mount();
  const long = Array.from({ length: 12 }, (_, index) => `line ${index + 1}`).join("\n");
  await setup.mockInput.typeText("check this ");
  await setup.mockInput.pasteBracketedText(long);
  await until(setup, () => setup.captureCharFrame().includes("[Pasted text #1 +12 lines]"));
  expect(setup.captureCharFrame()).not.toContain("line 7");
  await setup.mockInput.pressEnter();
  await until(setup, () => fake.commands.some((command) => command.type === "prompt.submit"));
  expect(fake.commands.find((command) => command.type === "prompt.submit")).toMatchObject({ text: `check this ${long}` });
});

test("a short paste goes into the box as it is", async () => {
  const { setup } = await mount();
  await setup.mockInput.pasteBracketedText("short paste");
  await until(setup, () => setup.captureCharFrame().includes("short paste"));
  expect(setup.captureCharFrame()).not.toContain("Pasted text");
});
