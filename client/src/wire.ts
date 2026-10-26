import { decodeEnvelope } from "./decode";
import type { Command, Envelope, ErrorInfo } from "./protocol";
import { PROTOCOL_VERSION } from "./protocol";

export const MAX_MESSAGE_BYTES = 4 * 1024 * 1024;
const REQUEST_TIMEOUT_MS = 15_000;

export class CommandRejected extends Error {
  constructor(readonly error: ErrorInfo) {
    super(`${error.code}: ${error.message}`);
  }
}

export class ConnectionClosed extends Error {}

interface Pending {
  resolve: (envelope: Envelope) => void;
  reject: (error: Error) => void;
}

export class Wire {
  private readonly pending = new Map<string, Pending>();
  private readonly queue: (Envelope | null)[] = [];
  private waiter: ((value: Envelope | null) => void) | null = null;

  private constructor(
    private readonly socket: WebSocket,
    private readonly room: string,
  ) {
    socket.addEventListener("message", (message) => this.receive(message.data));
    socket.addEventListener("close", () => this.finish());
    socket.addEventListener("error", () => this.finish());
  }

  static open(url: string, room: string): Promise<Wire> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      const failed = () => reject(new ConnectionClosed("cannot connect"));
      socket.addEventListener("error", failed, { once: true });
      socket.addEventListener(
        "open",
        () => {
          socket.removeEventListener("error", failed);
          resolve(new Wire(socket, room));
        },
        { once: true },
      );
    });
  }

  async request(command: Command, token: string | null): Promise<void> {
    const envelope: Envelope = {
      v: PROTOCOL_VERSION,
      id: `c_${randomHex(10)}`,
      kind: "cmd",
      type: command.type,
      room: this.room,
      ts: new Date().toISOString(),
      actor: null,
      seq: null,
      to: null,
      token,
      re: null,
      ok: null,
      error: null,
      payload: payloadOf(command),
    };
    const reply = new Promise<Envelope>((resolve, reject) => {
      this.pending.set(envelope.id, { resolve, reject });
    });
    const timer = setTimeout(
      () => this.settle(envelope.id, new ConnectionClosed("request timed out")),
      REQUEST_TIMEOUT_MS,
    );
    try {
      this.socket.send(JSON.stringify(envelope));
      const ack = await reply;
      if (ack.ok !== true) {
        throw new CommandRejected(ack.error ?? { code: "internal", message: "rejected" });
      }
    } finally {
      clearTimeout(timer);
      this.pending.delete(envelope.id);
    }
  }

  async *envelopes(): AsyncGenerator<Envelope> {
    for (;;) {
      const next = this.queue.shift();
      if (next === undefined) {
        const value = await new Promise<Envelope | null>((resolve) => {
          this.waiter = resolve;
        });
        if (value === null) {
          return;
        }
        yield value;
      } else if (next === null) {
        return;
      } else {
        yield next;
      }
    }
  }

  close(): void {
    this.socket.close();
    this.finish();
  }

  private receive(data: unknown): void {
    if (typeof data !== "string" || data.length > MAX_MESSAGE_BYTES) {
      return;
    }
    const envelope = decodeEnvelope(data);
    if (envelope === null) {
      return;
    }
    if (envelope.kind === "ack" && envelope.re !== null) {
      this.pending.get(envelope.re)?.resolve(envelope);
      return;
    }
    this.push(envelope);
  }

  private push(value: Envelope | null): void {
    const waiter = this.waiter;
    if (waiter !== null) {
      this.waiter = null;
      waiter(value);
    } else {
      this.queue.push(value);
    }
  }

  private finish(): void {
    this.push(null);
    for (const [id] of this.pending) {
      this.settle(id, new ConnectionClosed("connection closed"));
    }
  }

  private settle(id: string, error: Error): void {
    this.pending.get(id)?.reject(error);
  }
}

function payloadOf(command: Command): Envelope["payload"] {
  const { type: _type, ...rest } = command;
  return rest as Envelope["payload"];
}

function randomHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return Array.from(buffer, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
