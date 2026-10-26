import { afterAll, beforeAll, expect, test } from "bun:test";
import { testRender } from "@opentui/react/test-utils";
import { parseLink, SessionClient } from "@plural/client";
import { App } from "../src/App";
import { startHost, type RunningHost } from "../../client/test/support/host";

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

type Setup = Awaited<ReturnType<typeof testRender>>;

let host: RunningHost;
beforeAll(async () => {
  host = await startHost("review");
}, 60_000);
afterAll(async () => {
  await host.stop();
});

async function open(link: string, name: string): Promise<{ client: SessionClient; setup: Setup }> {
  const client = new SessionClient(parseLink(link), { name, client: { kind: "tui", version: "test" } });
  const setup = await testRender(
    <App client={client} room="r" version="test" guestLink={null} onQuit={() => undefined} />,
    { width: 120, height: 40 },
  );
  await setup.renderOnce();
  return { client, setup };
}

async function until(setup: Setup, predicate: (frame: string) => boolean, timeoutMs = 20_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    await setup.renderOnce();
    const frame = setup.captureCharFrame();
    if (predicate(frame)) {
      return frame;
    }
    if (Date.now() > deadline) {
      throw new Error(`condition not met in time:\n${frame}`);
    }
    await tick(25);
  }
}

test("a guest proposes, the host approves from the keyboard and the tool runs", async () => {
  const owner = await open(host.hostLink, "vlad");
  const guest = new SessionClient(parseLink(host.guestLink), { name: "alia", client: { kind: "test", version: "0" } });
  const pump = (async () => {
    try {
      for await (const _event of guest.events()) {
        void _event;
      }
    } catch {
      return;
    }
  })();
  await until(owner.setup, (frame) => frame.includes("alia"));

  while (guest.status !== "online") {
    await tick(25);
  }
  await guest.send({ type: "prompt.submit", text: "$ cat notes.txt" });

  await until(owner.setup, (frame) => frame.includes("alia proposes"));
  await owner.setup.mockInput.pressTab();
  await until(owner.setup, (frame) => frame.includes("edit first"));
  await tick(500);
  await owner.setup.mockInput.pressKey("y");

  await until(owner.setup, (frame) => frame.includes("approval needed"));
  await owner.setup.mockInput.pressKey("y");
  await tick(100);
  expect(owner.setup.captureCharFrame()).toContain("approval needed");

  await tick(500);
  await owner.setup.mockInput.pressKey("y");
  const seen = await until(owner.setup, (frame) => frame.includes("alpha"));
  expect(seen).toContain("cat notes.txt");
  expect(seen).toContain("alia");

  guest.close();
  await pump;
  owner.client.close();
  owner.setup.renderer.destroy();
}, 90_000);
