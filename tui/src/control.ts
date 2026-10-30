import type { AgentConfig, Preset } from "./presets";

export interface ControlResult {
  ok: boolean;
  agent?: string;
  message?: string;
  error?: string;
  presets?: Preset[];
}

export interface AgentControl {
  configure(config: AgentConfig): Promise<ControlResult>;
  test(config: AgentConfig): Promise<ControlResult>;
  /** The host's provider catalog, which the client renders and keeps no copy of. */
  catalog(): Promise<Preset[]>;
}

export const CONTROL_TIMEOUT_MS = 60_000;

export class ControlLink implements AgentControl {
  private counter = 0;
  private readonly pending = new Map<string, (result: ControlResult) => void>();
  private buffered = "";

  constructor(private readonly write: (line: string) => boolean) {}

  receive(chunk: string): void {
    this.buffered += chunk;
    const lines = this.buffered.split("\n");
    this.buffered = lines.pop() ?? "";
    for (const line of lines) {
      this.dispatch(line);
    }
  }

  close(): void {
    for (const [id, resolve] of this.pending) {
      resolve({ ok: false, error: "the host stopped" });
      this.pending.delete(id);
    }
  }

  configure(config: AgentConfig): Promise<ControlResult> {
    return this.request("configure", config);
  }

  test(config: AgentConfig): Promise<ControlResult> {
    return this.request("test", config);
  }

  async catalog(): Promise<Preset[]> {
    const result = await this.request("catalog", null);
    return result.ok ? (result.presets ?? []) : [];
  }

  private request(type: "configure" | "test" | "catalog", config: AgentConfig | null): Promise<ControlResult> {
    this.counter += 1;
    const id = `k${this.counter}`;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        resolve({ ok: false, error: "the host did not answer in time" });
      }, CONTROL_TIMEOUT_MS);
      this.pending.set(id, (result) => {
        clearTimeout(timer);
        resolve(result);
      });
      if (!this.write(`${JSON.stringify(config === null ? { id, type } : { id, type, config })}\n`)) {
        this.pending.delete(id);
        clearTimeout(timer);
        resolve({ ok: false, error: "the host is not reachable" });
      }
    });
  }

  private dispatch(line: string): void {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line) as Record<string, unknown>;
    } catch {
      return;
    }
    const id = message["id"];
    if (message["type"] !== "result" || typeof id !== "string") {
      return;
    }
    const resolve = this.pending.get(id);
    if (!resolve) {
      return;
    }
    this.pending.delete(id);
    resolve({
      ok: message["ok"] === true,
      ...(typeof message["agent"] === "string" ? { agent: message["agent"] } : {}),
      ...(typeof message["message"] === "string" ? { message: message["message"] } : {}),
      ...(typeof message["error"] === "string" ? { error: message["error"] } : {}),
      ...(Array.isArray(message["presets"]) ? { presets: message["presets"] as Preset[] } : {}),
    });
  }
}
