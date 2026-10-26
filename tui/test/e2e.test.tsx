import { render } from "ink-testing-library";
import { afterAll, beforeAll, expect, test } from "vitest";
import { parseLink, SessionClient } from "@plural/client";
import { App } from "../src/App";
import { startHost, type RunningHost } from "../../client/test/support/host";

const tick = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function until(predicate: () => boolean, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) {
      throw new Error("condition was not met in time");
    }
    await tick(25);
  }
}

let host: RunningHost;
beforeAll(async () => {
  host = await startHost("review");
}, 60_000);
afterAll(async () => {
  await host.stop();
});

function open(link: string, name: string) {
  const client = new SessionClient(parseLink(link), { name, client: { kind: "tui", version: "test" } });
  const app = render(<App client={client} room="r" version="test" guestLink={null} />);
  return { client, app, text: () => app.frames.join("\n") };
}

test("a guest proposes, the host approves from the keyboard and both see the tool run", async () => {
  const owner = open(host.hostLink, "vlad");
  const guest = open(host.guestLink, "alia");
  await until(() => owner.client.projection.me !== undefined && guest.client.projection.me !== undefined);

  for (const char of "$ cat notes.txt") {
    guest.app.stdin.write(char);
    await tick(5);
  }
  guest.app.stdin.write("\r");

  await until(() => (owner.app.lastFrame() ?? "").includes("alia proposes"));
  owner.app.stdin.write("\t");
  await tick(100);
  owner.app.stdin.write("y");

  await until(() => (owner.app.lastFrame() ?? "").includes("approval needed"));
  owner.app.stdin.write("y");
  await tick(100);
  expect(owner.app.lastFrame()).toContain("approval needed");

  await tick(500);
  owner.app.stdin.write("y");
  await until(() => owner.text().includes("alpha") && guest.text().includes("alpha"));
  expect(guest.text()).toContain("approved by host");
  expect(owner.text()).toContain("cat notes.txt");

  owner.app.unmount();
  guest.app.unmount();
}, 90_000);
