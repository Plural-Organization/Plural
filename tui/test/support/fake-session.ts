import { Projection, type Command, type ConnectionStatus, type Event, type EventRecord, type Session } from "@plural/client";

export class FakeSession implements Session {
  readonly projection = new Projection();
  readonly sent: Command[] = [];

  get commands(): Command[] {
    return this.sent.filter((command) => command.type !== "presence.typing");
  }

  status: ConnectionStatus = "online";
  private seq = 0;
  private queue: Event[] = [];
  private wake: (() => void) | null = null;
  private closed = false;

  onStatus(): () => void {
    return () => undefined;
  }

  async send(command: Command): Promise<void> {
    this.sent.push(command);
  }

  close(): void {
    this.closed = true;
    this.wake?.();
  }

  emit(event: Event): void {
    if (event.type === "message.delta" || event.type === "participant.typing" || event.type === "tool.output") {
      this.projection.observe(event);
    } else if (event.type === "session.snapshot") {
      this.projection.load(event.state, event.streaming, event.typing);
    } else if (event.type === "session.welcome") {
      this.projection.meId = event.participant.id;
      this.projection.agent = event.agent;
    } else if (!event.type.startsWith("invite.") && event.type !== "error") {
      this.seq += 1;
      const record: EventRecord = { seq: this.seq, id: `e${this.seq}`, ts: new Date().toISOString(), actor_id: null, event };
      this.projection.apply(record);
    }
    this.queue.push(event);
    this.wake?.();
  }

  async *events(): AsyncGenerator<Event> {
    while (!this.closed) {
      const next = this.queue.shift();
      if (next) {
        yield next;
      } else {
        await new Promise<void>((resolve) => {
          this.wake = resolve;
        });
      }
    }
  }
}

export const HOST = { id: "p_host", name: "vlad", role: "host", connected: true } as const;
export const ALIA = { id: "p_alia", name: "Alia", role: "participant", connected: true } as const;
export const CALL = { id: "t1", name: "bash", risk: "exec", subject: "rm a.txt", args: {} } as const;
export const GUEST = { initiator_id: "p_alia", initiator_role: "participant", origin: "direct" } as const;
