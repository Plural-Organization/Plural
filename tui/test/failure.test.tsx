import { afterEach, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { CommandRejected } from "@plural/client";
import { App } from "../src/App";
import { explain } from "../src/failure";
import { FakeSession } from "./support/fake-session";

type Setup = Awaited<ReturnType<typeof testRender>>;
const open: Setup[] = [];
afterEach(() => {
  while (open.length > 0) {
    open.pop()?.renderer.destroy();
  }
});

const rejected = (code: string, message: string) => new CommandRejected({ code, message } as never);

test("a used or expired invite is said in plain words with what to do", () => {
  const text = explain(rejected("unauthorized", "invite is invalid or expired"));
  expect(text).toContain("already used or has expired");
  expect(text).toContain("/invite");
});

test("other refusals are explained too", () => {
  expect(explain(rejected("unauthorized", "access revoked"))).toContain("removed you");
  expect(explain(rejected("unauthorized", "token expired"))).toContain("not valid any more");
  expect(explain(rejected("forbidden", "viewer cannot prompt.submit"))).toContain("does not allow");
  expect(explain(rejected("version_mismatch", "protocol 2"))).toContain("plural update");
  expect(explain(rejected("internal", "boom"))).toBe("internal: boom");
  expect(explain(new Error("plain failure"))).toBe("plain failure");
});

class Refused extends FakeSession {
  override async *events(): AsyncGenerator<never> {
    throw rejected("unauthorized", "invite is invalid or expired");
  }
}

async function mount(fake: FakeSession): Promise<Setup> {
  const setup = await testRender(<App client={fake} room="r_1" version="0.2.2" guestLink={null} splash onQuit={() => undefined} />, { width: 100, height: 40 });
  open.push(setup);
  await setup.renderOnce();
  return setup;
}

async function frame(setup: Setup, includes: string, timeout = 4000): Promise<string> {
  const deadline = Date.now() + timeout;
  for (;;) {
    await setup.renderOnce();
    const text = setup.captureCharFrame();
    if (text.includes(includes)) {
      return text;
    }
    if (Date.now() > deadline) {
      throw new Error(`"${includes}" never appeared in:\n${text}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

test("a refused join shows the reason on the opening screen instead of reconnecting forever", async () => {
  const fake = new Refused();
  fake.status = "offline";
  const setup = await mount(fake);
  await setup.mockInput.pressKey("x");
  const text = await frame(setup, "could not join");
  expect(text).toContain("already used or has expired");
  expect(text).toContain("enter or ctrl+c to leave");
  expect(text).not.toContain("reconnecting");
});

test("enter leaves from that screen", async () => {
  const quits: number[] = [];
  const fake = new Refused();
  fake.status = "offline";
  const setup = await testRender(<App client={fake} room="r_1" version="0.2.2" guestLink={null} splash onQuit={() => quits.push(1)} />, { width: 100, height: 40 });
  open.push(setup);
  await setup.renderOnce();
  await setup.mockInput.pressKey("x");
  await frame(setup, "could not join");
  await setup.mockInput.pressEnter();
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(quits).toEqual([1]);
});

test("before the first connection the wait is not called a reconnection", async () => {
  const fake = new FakeSession();
  fake.status = "offline";
  const setup = await mount(fake);
  await setup.mockInput.pressKey("x");
  const text = await frame(setup, "still trying");
  expect(text).toContain("cannot reach the host yet");
  expect(text).not.toContain("reconnecting");
});
