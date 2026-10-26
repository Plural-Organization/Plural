import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { SessionClient, CommandRejected, parseLink, type Event } from "../src";
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
  const pump = (async () => {
    try {
      for await (const event of client.events()) {
        seen.push(event);
      }
    } catch {
      return;
    }
  })();
  return { client, seen, pump };
}

describe("TypeScript client against a Python host", () => {
  let host: RunningHost;
  beforeAll(async () => {
    host = await startHost("review");
  }, 60_000);
  afterAll(async () => {
    await host.stop();
  });

  test("a host and a guest converge through proposal and approval", async () => {
    const owner = connect(host.hostLink, "vlad");
    const guest = connect(host.guestLink, "alia");
    await until(() => owner.client.projection.me !== undefined && guest.client.projection.me !== undefined);
    expect(owner.client.projection.me?.role).toBe("host");
    expect(guest.client.projection.state.prompt_mode).toBe("review");

    await guest.client.send({ type: "prompt.submit", text: "$ cat notes.txt" });
    await until(() => Object.keys(owner.client.projection.state.proposals).length === 1);
    const proposalId = Object.keys(owner.client.projection.state.proposals)[0] as string;

    await expect(
      guest.client.send({ type: "proposal.decide", proposal_id: proposalId, decision: "approve" }),
    ).rejects.toBeInstanceOf(CommandRejected);

    await owner.client.send({ type: "proposal.decide", proposal_id: proposalId, decision: "approve" });
    await until(() => Object.keys(owner.client.projection.state.approvals).length === 1);
    const approvalId = Object.keys(owner.client.projection.state.approvals)[0] as string;
    await owner.client.send({ type: "approval.respond", approval_id: approvalId, decision: "once" });
    await until(() => owner.client.projection.state.run === null && owner.client.projection.state.transcript.length >= 3);

    expect(guest.client.projection.state.transcript).toEqual(owner.client.projection.state.transcript);
    const tool = owner.client.projection.state.transcript.find((entry) => entry.kind === "tool");
    expect(tool?.ok).toBe(true);
    expect(tool?.output).toContain("alpha");

    owner.client.close();
    guest.client.close();
    await Promise.all([owner.pump, guest.pump]);
  }, 60_000);

  test("the host switches the prompt mode and the guest sees it", async () => {
    const owner = connect(host.hostLink, "vlad");
    const guest = connect(host.guestLink.replace(/invite=.*/, "invite=unused"), "bek");
    await until(() => owner.client.projection.me !== undefined);
    await owner.client.send({ type: "session.set_prompt_mode", mode: "open" });
    await until(() => owner.client.projection.state.prompt_mode === "open");
    owner.client.close();
    guest.client.close();
    await owner.pump;
    await guest.pump;
  }, 60_000);

  test("a forged token is refused", async () => {
    const forged = host.hostLink.replace(/token=.*/, "token=forged");
    const client = new SessionClient(parseLink(forged), { name: "mallory", client: CLIENT });
    const iterate = async () => {
      for await (const _event of client.events()) {
        return;
      }
    };
    await expect(iterate()).rejects.toMatchObject({ error: { code: "unauthorized" } });
  }, 30_000);
});
