import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { SessionClient, parseLink, type ConnectionStatus } from "../src";
import { startHost, startRelay, type RunningHost, type RunningRelay } from "./support/host";

const CLIENT = { kind: "test", version: "0" };

async function until(predicate: () => boolean, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) {
      throw new Error("condition was not met in time");
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

function join(link: string, name: string) {
  const client = new SessionClient(parseLink(link), { name, client: CLIENT });
  const statuses: ConnectionStatus[] = [];
  client.onStatus((status) => statuses.push(status));
  const pump = (async () => {
    try {
      for await (const _event of client.events()) {
        continue;
      }
    } catch {
      return;
    }
  })();
  return { client, statuses, pump };
}

describe("clients through a relay that restarts", () => {
  let relay: RunningRelay;
  let host: RunningHost;

  beforeAll(async () => {
    relay = await startRelay();
    host = await startHost("open", relay.url);
  }, 90_000);

  afterAll(async () => {
    await host.stop();
    await relay.stop();
  });

  test("guests see a reconnection, keep their seat and hear the host again", async () => {
    const owner = join(host.hostLink, "vlad");
    const guest = join(host.guestLink, "alia");
    await until(() => owner.client.projection.me !== undefined && guest.client.projection.me !== undefined);
    const seat = guest.client.projection.me?.id;
    expect(guest.statuses).toContain("online");

    await relay.stop();
    await until(() => guest.client.status === "offline");
    expect(guest.client.status).toBe("offline");

    relay = await startRelay(relay.port);
    await until(() => guest.client.status === "online" && owner.client.status === "online");
    expect(guest.statuses.slice(-3)).toEqual(["online", "offline", "online"]);
    expect(guest.client.projection.me?.id).toBe(seat);

    await owner.client.send({ type: "session.set_prompt_mode", mode: "review" });
    await until(() => guest.client.projection.state.prompt_mode === "review");

    owner.client.close();
    guest.client.close();
    await Promise.all([owner.pump, guest.pump]);
  }, 120_000);
});
