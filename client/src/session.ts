import { decodeEvent, decodeRecord, ProtocolError } from "./decode";
import type { JoinLink } from "./link";
import { Projection } from "./projection";
import type { ClientInfo, Command, Envelope, ErrorCode, Event } from "./protocol";
import { CommandRejected, ConnectionClosed, Wire } from "./wire";

const INITIAL_DELAY_MS = 250;
const MAX_DELAY_MS = 2000;
const FATAL = new Set<ErrorCode>(["unauthorized", "forbidden", "version_mismatch"]);

export type ConnectionStatus = "connecting" | "online" | "offline";

export interface SessionOptions {
  name: string;
  client: ClientInfo;
  onWelcome?: (welcome: { room: string; token: string }) => void;
}

export interface Session {
  readonly projection: Projection;
  readonly status: ConnectionStatus;
  onStatus(listener: (status: ConnectionStatus) => void): () => void;
  events(): AsyncIterable<Event>;
  send(command: Command): Promise<void>;
  close(): void;
}

export class SessionClient implements Session {
  readonly projection = new Projection();
  private token: string | null;
  private wire: Wire | null = null;
  private closed = false;
  private current: ConnectionStatus = "connecting";
  private readonly listeners = new Set<(status: ConnectionStatus) => void>();

  constructor(
    private readonly link: JoinLink,
    private readonly options: SessionOptions,
  ) {
    this.token = link.token;
  }

  get status(): ConnectionStatus {
    return this.current;
  }

  onStatus(listener: (status: ConnectionStatus) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private setStatus(status: ConnectionStatus): void {
    if (status !== this.current) {
      this.current = status;
      this.listeners.forEach((listener) => listener(status));
    }
  }

  async send(command: Command): Promise<void> {
    if (this.wire === null) {
      throw new ConnectionClosed("not connected");
    }
    await this.wire.request(command, this.token);
  }

  close(): void {
    this.closed = true;
    this.wire?.close();
  }

  async *events(): AsyncGenerator<Event> {
    let delay = INITIAL_DELAY_MS;
    while (!this.closed) {
      try {
        const wire = await Wire.open(this.link.url, this.link.room);
        try {
          await wire.request(this.hello(), null);
          this.wire = wire;
          this.setStatus("online");
          delay = INITIAL_DELAY_MS;
          for await (const envelope of wire.envelopes()) {
            const event = this.absorb(envelope);
            if (event !== null) {
              yield event;
            }
          }
        } finally {
          this.wire = null;
          this.setStatus("offline");
          wire.close();
        }
      } catch (error) {
        this.setStatus("offline");
        if (error instanceof CommandRejected && FATAL.has(error.error.code)) {
          throw error;
        }
        if (!(error instanceof ConnectionClosed || error instanceof CommandRejected)) {
          throw error;
        }
      }
      if (this.closed) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, MAX_DELAY_MS);
    }
  }

  private hello(): Command {
    return {
      type: "session.hello",
      client: this.options.client,
      name: this.options.name,
      invite: this.token === null ? this.link.invite : null,
      token: this.token,
      since: this.projection.ready ? this.projection.state.last_seq : null,
    };
  }

  private absorb(envelope: Envelope): Event | null {
    let event: Event;
    let record;
    try {
      record = decodeRecord(envelope);
      event = record === null ? decodeEvent(envelope) : record.event;
    } catch (error) {
      if (error instanceof ProtocolError) {
        return null;
      }
      throw error;
    }
    if (record !== null) {
      return this.projection.apply(record) ? event : null;
    }
    switch (event.type) {
      case "session.welcome":
        this.token = event.token;
        this.options.onWelcome?.({ room: event.room, token: event.token });
        this.projection.meId = event.participant.id;
        this.projection.basePolicy = event.base_policy;
        this.projection.agent = event.agent;
        break;
      case "session.snapshot":
        this.projection.load(event.state, event.streaming, event.typing);
        break;
      default:
        this.projection.observe(event);
    }
    return event;
  }
}
