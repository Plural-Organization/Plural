import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { CommandRejected, parseLink, SessionClient, type Event } from "../src";
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
  const seen: Event[] = [];
  let failure: unknown = null;
  const pump = (async () => {
    try {
      for await (const event of client.events()) {
        seen.push(event);
      }
    } catch (error) {
      failure = error;
    }
  })();
  return { client, seen, pump, failure: () => failure };
}

describe("the room link against a Python host that approves", () => {
  let host: RunningHost;
  beforeAll(async () => {
    host = await startHost("open", undefined, "approve");
  }, 60_000);
  afterAll(async () => {
    await host.stop();
  });

  test("a guest waits, the host lets them in and they are in", async () => {
    const owner = connect(host.hostLink, "vlad");
    await until(() => owner.client.projection.me !== undefined);
    const guest = connect(host.guestLink, "alia");
    await until(() => guest.client.projection.waiting);
    expect(guest.client.projection.me).toBeUndefined();
    await until(() => Object.keys(owner.client.projection.state.join_requests).length === 1);
    const [request] = Object.values(owner.client.projection.state.join_requests);
    expect(request?.name).toBe("alia");

    await owner.client.send({ type: "join.decide", request_id: request!.id, decision: "viewer" });
    await until(() => guest.client.projection.me !== undefined);
    expect(guest.client.projection.me?.role).toBe("viewer");
    expect(guest.client.projection.waiting).toBe(false);
    expect(Object.keys(owner.client.projection.state.join_requests)).toHaveLength(0);
    expect(guest.client.projection.state.join_requests).toEqual({});

    owner.client.close();
    guest.client.close();
    await Promise.all([owner.pump, guest.pump]);
  }, 60_000);

  test("a refusal ends the wait with the host's words, and the host can ask for the same link again", async () => {
    const owner = connect(host.hostLink, "vlad");
    await until(() => owner.client.projection.me !== undefined);
    const guest = connect(host.guestLink, "mallory");
    await until(() => Object.keys(owner.client.projection.state.join_requests).length === 1);
    const [request] = Object.values(owner.client.projection.state.join_requests);
    await owner.client.send({ type: "join.decide", request_id: request!.id, decision: "deny" });
    await guest.pump;
    expect(guest.failure()).toBeInstanceOf(CommandRejected);
    expect(String(guest.failure())).toContain("did not let you in");

    await owner.client.send({ type: "invite.create", role: "participant", ttl_s: 3600, reusable: true });
    await until(() => owner.seen.some((event) => event.type === "invite.created" && event.reusable));
    const created = owner.seen.find((event) => event.type === "invite.created" && event.reusable);
    expect(created?.type === "invite.created" ? created.link : "").toBe(host.guestLink);
    expect(created?.type === "invite.created" ? created.expires_at : "x").toBeNull();

    owner.client.close();
    await owner.pump;
  }, 60_000);

  test("with the room open the same link goes straight in", async () => {
    const owner = connect(host.hostLink, "vlad");
    await until(() => owner.client.projection.me !== undefined);
    await owner.client.send({ type: "link.set_admission", mode: "open" });
    await until(() => owner.client.projection.state.admission === "open");
    const guest = connect(host.guestLink, "bek");
    await until(() => guest.client.projection.me !== undefined);
    expect(guest.client.projection.me?.role).toBe("participant");
    owner.client.close();
    guest.client.close();
    await Promise.all([owner.pump, guest.pump]);
  }, 60_000);
});
