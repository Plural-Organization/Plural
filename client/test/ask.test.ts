import { describe, expect, test } from "vitest";
import { askTeammate, CommandRejected, Projection, type Command, type ConnectionStatus, type Event, type Session } from "../src";

// A teammate's host that plays the given events once the request arrives.
class Room implements Session {
  readonly projection = new Projection();
  readonly sent: Command[] = [];
  status: ConnectionStatus = "online";
  closed = false;
  private queue: Event[] = [];
  private wake: (() => void) | null = null;

  constructor(
    private readonly reply: (room: Room) => void,
    private readonly refuse: string | null = null,
  ) {
    this.projection.meId = "p_me";
  }

  onStatus(): () => void {
    return () => undefined;
  }

  emit(event: Event): void {
    this.queue.push(event);
    this.wake?.();
  }

  async send(command: Command): Promise<void> {
    this.sent.push(command);
    if (this.refuse !== null) {
      throw new CommandRejected({ code: "conflict", message: this.refuse } as never);
    }
    this.reply(this);
  }

  close(): void {
    this.closed = true;
    this.wake?.();
  }

  async *events(): AsyncGenerator<Event> {
    this.emit({ type: "participant.typing", participant_id: "p_host", typing: false } as Event);
    while (!this.closed) {
      const next = this.queue.shift();
      if (next !== undefined) {
        yield next;
      } else {
        await new Promise<void>((resolve) => {
          this.wake = resolve;
        });
      }
    }
  }
}

const asked = { id: "b_1", participant_id: "p_me", name: "me", focus: "how does /orders work?", update: false, requested_at: "2026-11-07T12:00:00Z" };
const granted = { type: "briefing.resolved", request_id: "b_1", participant_id: "p_me", decision: "granted", decided_by: "p_host" } as Event;
const delivered = (over: Record<string, unknown> = {}) =>
  ({ type: "briefing.delivered", request_id: "b_1", to: "p_me", text: "It takes an order id and returns the invoice.", as_of_seq: 42, update: false, error: null, ...over }) as Event;

describe("asking a teammate's agent", () => {
  test("the question goes in one request, the answer comes back with who wrote it, and the visit ends", async () => {
    const room = new Room((r) => {
      r.emit({ type: "briefing.requested", request: asked } as Event);
      r.emit(granted);
      r.emit(delivered());
    });
    const progress: string[] = [];
    const briefing = await askTeammate(room, { focus: "how does /orders work?", update: false }, { from: "alia", onProgress: (text) => progress.push(text) });
    expect(briefing).toEqual({ from: "alia", text: "It takes an order id and returns the invoice.", asOf: 42, update: false });
    expect(room.sent).toEqual([{ type: "briefing.request", focus: "how does /orders work?", update: false }]);
    expect(progress).toEqual(["waiting for alia to agree", "alia agreed, their agent is writing it"]);
    expect(room.closed).toBe(true);
  });

  test("an answer meant for someone else is not mine", async () => {
    const room = new Room((r) => {
      r.emit(delivered({ to: "p_cleo", text: "for cleo" }));
      r.emit(delivered());
    });
    expect((await askTeammate(room, { focus: null, update: false }, { from: "alia" })).text).toBe("It takes an order id and returns the invoice.");
  });

  test("a refusal, a failed write and a refused request are told in the teammate's name, and the visit ends", async () => {
    const no = new Room((r) => r.emit({ ...granted, decision: "denied" } as Event));
    await expect(askTeammate(no, { focus: null, update: false }, { from: "alia" })).rejects.toThrow("alia said no to the briefing");
    expect(no.closed).toBe(true);
    const broken = new Room((r) => r.emit(delivered({ error: "the model could not write it" })));
    await expect(askTeammate(broken, { focus: null, update: false }, { from: "alia" })).rejects.toThrow("alia's briefing could not be written: the model could not write it");
    const cooling = new Room(() => undefined, "wait a minute between briefings");
    await expect(askTeammate(cooling, { focus: null, update: false }, { from: "alia" })).rejects.toThrow("wait a minute between briefings");
    expect(cooling.closed).toBe(true);
  });

  test("a host that never answers is given up on, and the visit ends", async () => {
    const silent = new Room(() => undefined);
    await expect(askTeammate(silent, { focus: null, update: false }, { from: "alia", waitMs: 30 })).rejects.toThrow("alia did not answer");
    expect(silent.closed).toBe(true);
  });

  test("a connection that closes first says so", async () => {
    const room = new Room((r) => r.close());
    await expect(askTeammate(room, { focus: null, update: false }, { from: "alia" })).rejects.toThrow("the connection to alia closed before the briefing came");
  });
});
