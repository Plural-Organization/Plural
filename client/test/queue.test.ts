import { afterAll, beforeAll, expect, test } from "vitest";
import { parseLink, SessionClient } from "../src";
import { startHost, type RunningHost } from "./support/host";

const CLIENT = { kind: "test", version: "0" };

async function until(predicate: () => boolean, timeoutMs = 15_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) {
      throw new Error("condition was not met in time");
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

function connect(link: string, name: string) {
  const client = new SessionClient(parseLink(link), { name, client: CLIENT });
  const pump = (async () => {
    try {
      for await (const _event of client.events()) {
        void _event;
      }
    } catch {
      return;
    }
  })();
  return { client, pump };
}

let host: RunningHost;
beforeAll(async () => {
  host = await startHost("open");
}, 60_000);
afterAll(async () => {
  await host.stop();
});

test("typing and the prompt queue reach every client and the queue drains", async () => {
  const owner = connect(host.hostLink, "vlad");
  const guest = connect(host.guestLink, "alia");
  await until(() => owner.client.projection.me !== undefined && guest.client.projection.me !== undefined);
  const guestId = guest.client.projection.meId as string;

  await guest.client.send({ type: "presence.typing", typing: true });
  await until(() => owner.client.projection.typing.has(guestId));
  await guest.client.send({ type: "presence.typing", typing: false });
  await until(() => !owner.client.projection.typing.has(guestId));

  await owner.client.send({ type: "prompt.submit", text: "$ cat notes.txt" });
  await until(() => Object.keys(owner.client.projection.state.approvals).length === 1);
  await guest.client.send({ type: "prompt.submit", text: "and then summarise it" });
  await until(() => owner.client.projection.state.queue.length === 1);
  expect(owner.client.projection.state.queue[0]).toMatchObject({ author_id: guestId, text: "and then summarise it" });
  await until(() => guest.client.projection.state.queue.length === 1);

  const approvalId = Object.keys(owner.client.projection.state.approvals)[0] as string;
  await owner.client.send({ type: "approval.respond", approval_id: approvalId, decision: "once" });
  await until(() => owner.client.projection.state.queue.length === 0);
  await until(() => guest.client.projection.state.queue.length === 0);

  owner.client.close();
  guest.client.close();
  await Promise.all([owner.pump, guest.pump]);
}, 60_000);
