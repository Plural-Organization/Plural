import { spawn } from "node:child_process";
import { hostCommand } from "./host-process";

// The chat apps this computer can connect, as `plural-host bridge list --json` reports them. The terminal keeps
// no list of services or of the fields each needs: that list is the host's, so a new service appears here
// without a change to this file. Values go to the host on standard input, so a token never shows in a process list.

export type BridgeState = "off" | "starting" | "running" | "failed" | "idle";

export interface BridgeField {
  id: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
  placeholder: string;
}

export interface BridgeApp {
  id: string;
  label: string;
  summary: string;
  steps: string[];
  fields: BridgeField[];
  configured: boolean;
  enabled: boolean;
  state: BridgeState;
  identity: string;
  error: string;
  values: Record<string, string>;
  set: string[];
  owners: { id: string; name: string }[];
  pairing: string | null;
  chats: number;
  links: { open: string; invite: string; autopair: boolean };
}

export interface BridgeResult {
  ok: boolean;
  error?: string;
  identity?: string;
  pairing?: string;
}

export interface BridgeApi {
  list(): Promise<BridgeApp[]>;
  save(id: string, values: Record<string, string>, enabled?: boolean): Promise<BridgeResult>;
  test(id: string, values: Record<string, string>): Promise<BridgeResult>;
  remove(id: string): Promise<BridgeResult>;
  /** A new pairing code, to add one more owner. */
  renew(id: string): Promise<BridgeResult>;
}

export type Runner = (args: string[], stdin?: string) => Promise<{ code: number; out: string }>;

const TIMEOUT_MS = 45_000;

export const hostRunner: Runner = (args, stdin) =>
  new Promise((resolve) => {
    const [command, ...prefix] = hostCommand();
    let out = "";
    let done = false;
    const finish = (code: number, text: string): void => {
      if (!done) {
        done = true;
        clearTimeout(timer);
        resolve({ code, out: text });
      }
    };
    const child = spawn(command as string, [...prefix, "bridge", ...args], { stdio: ["pipe", "pipe", "pipe"] });
    const timer = setTimeout(() => {
      child.kill();
      finish(1, JSON.stringify({ ok: false, error: "the host did not answer in time" }));
    }, TIMEOUT_MS);
    child.stdout.on("data", (chunk: Buffer) => (out += chunk.toString()));
    child.on("error", () => finish(1, JSON.stringify({ ok: false, error: "plural-host is not reachable" })));
    child.on("close", (code) => finish(code ?? 1, out));
    child.stdin.on("error", () => undefined);
    child.stdin.end(stdin ?? "");
  });

function parse(out: string): Record<string, unknown> {
  const last = out.trim().split("\n").pop() ?? "";
  try {
    const value: unknown = JSON.parse(last);
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export function hostBridgeApi(run: Runner = hostRunner): BridgeApi {
  const result = async (args: string[], stdin?: string): Promise<BridgeResult> => {
    const { code, out } = await run(args, stdin);
    const body = parse(out);
    if (body["ok"] === true) {
      return {
        ok: true,
        ...(typeof body["identity"] === "string" ? { identity: body["identity"] } : {}),
        ...(typeof body["pairing"] === "string" ? { pairing: body["pairing"] } : {}),
      };
    }
    // An older host has no `bridge set --json`: typer says so on stderr and exits 2.
    const error = typeof body["error"] === "string" ? body["error"] : code === 2 ? "Update plural: the host does not know chat apps yet" : "it did not work";
    return { ok: false, error };
  };
  const withValues = (values: Record<string, string>): string => JSON.stringify({ values });
  return {
    async list() {
      const { out } = await run(["list", "--json"]);
      const body = parse(out);
      if (body["ok"] !== true || !Array.isArray(body["providers"])) {
        throw new Error("Update plural: the host does not know chat apps yet");
      }
      return body["providers"] as BridgeApp[];
    },
    save: (id, values, enabled) => result(["set", id, "--stdin", "--json", ...(enabled === undefined ? [] : [enabled ? "--enable" : "--disable"])], withValues(values)),
    test: (id, values) => result(["test", id, "--stdin", "--json"], withValues(values)),
    remove: (id) => result(["remove", id, "--json"]),
    renew: (id) => result(["pair", id, "--renew", "--json"]),
  };
}
