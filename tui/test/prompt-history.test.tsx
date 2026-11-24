import { afterEach, describe, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
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

const shows = (setup: Setup, text: string): boolean => setup.captureCharFrame().includes(text);

async function mount(history?: { initial: string[]; save: (entries: string[]) => void }): Promise<{ fake: FakeSession; setup: Setup }> {
  const fake = new FakeSession();
  fake.emit({ type: "session.welcome", room: "r_1", token: "t", participant: HOST, base_policy: [], agent: "demo" });
  fake.emit({ type: "participant.joined", participant: HOST });
  const setup = await testRender(
    <App client={fake} room="r_1" version="0.2.0" guestLink={null} onQuit={() => undefined} {...(history ? { history } : {})} />,
    { width: 120, height: 36 },
  );
  open.push(setup);
  await until(setup, () => shows(setup, "Message the agent"));
  return { fake, setup };
}

async function send(setup: Setup, fake: FakeSession, text: string): Promise<void> {
  const sent = (): number => fake.commands.filter((command) => command.type === "prompt.submit").length;
  const before = sent();
  await setup.mockInput.typeText(text);
  await setup.mockInput.pressEnter();
  await until(setup, () => sent() === before + 1);
}

describe("the up key in the composer", () => {
  test("counts down from the newest prompt as it goes back, and up again as it comes forward", async () => {
    const { fake, setup } = await mount();
    for (const text of ["first question", "second question", "third question"]) {
      await send(setup, fake, text);
    }

    await setup.mockInput.pressArrow("up");
    await until(setup, () => shows(setup, "history 3/3"));
    expect(setup.captureCharFrame()).toContain("› third question");

    await setup.mockInput.pressArrow("up");
    await until(setup, () => shows(setup, "history 2/3"));
    expect(setup.captureCharFrame()).toContain("› second question");

    await setup.mockInput.pressArrow("up");
    await until(setup, () => shows(setup, "history 1/3"));
    await setup.mockInput.pressArrow("up");
    await setup.renderOnce();
    expect(shows(setup, "history 1/3")).toBe(true);

    await setup.mockInput.pressArrow("down");
    await until(setup, () => shows(setup, "history 2/3"));
    await setup.mockInput.pressArrow("down");
    await setup.mockInput.pressArrow("down");
    await until(setup, () => !shows(setup, "history "));
  });

  test("escape leaves the list and gives back what was being typed", async () => {
    const { setup } = await mount({ initial: ["an older prompt", "an even older one"], save: () => undefined });
    await setup.mockInput.typeText("half a sentence");

    await setup.mockInput.pressArrow("up");
    await until(setup, () => shows(setup, "history 2/2"));
    expect(shows(setup, "› an older prompt")).toBe(true);

    await setup.mockInput.pressEscape();
    await until(setup, () => !shows(setup, "history "));
    expect(shows(setup, "half a sentence")).toBe(true);
  });

  test("prompts from the last session are there, and a new one is saved for the next", async () => {
    const saved: string[][] = [];
    const { fake, setup } = await mount({ initial: ["from yesterday"], save: (entries) => saved.push(entries) });

    await send(setup, fake, "from today");

    expect(saved.at(-1)).toEqual(["from today", "from yesterday"]);
    await setup.mockInput.pressArrow("up");
    await until(setup, () => shows(setup, "history 2/2"));
  });

  test("with nothing sent yet, up shows no list", async () => {
    const { setup } = await mount({ initial: [], save: () => undefined });
    await setup.mockInput.pressArrow("up");
    await setup.renderOnce();
    expect(shows(setup, "history ")).toBe(false);
  });
});
