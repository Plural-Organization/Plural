import type { ExtraStatus } from "./extras";
import type { AgentConfig, Preset } from "./presets";

export interface ControlResult {
  ok: boolean;
  agent?: string;
  message?: string;
  error?: string;
  presets?: Preset[];
  extras?: ExtraStatus[];
}

export interface AgentControl {
  configure(config: AgentConfig): Promise<ControlResult>;
  test(config: AgentConfig): Promise<ControlResult>;
  /** The host's provider catalog, which the client renders and keeps no copy of. */
  catalog(): Promise<Preset[]>;
  /** Which optional model SDKs the host has; empty when it does not say. */
  extras(): Promise<ExtraStatus[]>;
  /** Install one of them into the host's environment; this can take minutes on a slow network. */
  install(extra: string): Promise<ControlResult>;
}

export const CONTROL_TIMEOUT_MS = 60_000;
/** A little over the host's own install limit, so the host's answer is the one the user sees. */
export const INSTALL_TIMEOUT_MS = 11 * 60_000;

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

  async extras(): Promise<ExtraStatus[]> {
    const result = await this.request("catalog", null);
    return result.ok ? (result.extras ?? []) : [];
  }

  install(extra: string): Promise<ControlResult> {
    return this.request("install", null, { extra }, INSTALL_TIMEOUT_MS);
  }

  private request(
    type: "configure" | "test" | "catalog" | "install",
    config: AgentConfig | null,
    more: Record<string, string> = {},
    timeout: number = CONTROL_TIMEOUT_MS,
  ): Promise<ControlResult> {
    this.counter += 1;
    const id = `k${this.counter}`;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        resolve({ ok: false, error: "the host did not answer in time" });
      }, timeout);
      this.pending.set(id, (result) => {
        clearTimeout(timer);
        resolve(result);
      });
      if (!this.write(`${JSON.stringify(config === null ? { id, type, ...more } : { id, type, config, ...more })}\n`)) {
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
      ...(Array.isArray(message["extras"]) ? { extras: message["extras"] as ExtraStatus[] } : {}),
    });
  }
}
