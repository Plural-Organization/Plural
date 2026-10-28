import { networkInterfaces, type NetworkInterfaceInfo } from "node:os";

export type ShareMode = "local" | "network" | "relay";

export const SHARE_MODES: readonly ShareMode[] = ["local", "network", "relay"];

export function isShareMode(value: unknown): value is ShareMode {
  return typeof value === "string" && (SHARE_MODES as readonly string[]).includes(value);
}

export interface ShareChoice {
  share: ShareMode;
  relayUrl: string;
}

export interface ShareLaunch {
  args: string[];
  note: string | null;
}

const ADDRESS_FLAGS = ["--relay", "--public-url", "--bind"];

export function relayProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return "that is not a web address, use wss://relay.example.com";
  }
  if (url.protocol !== "wss:" && url.protocol !== "ws:") {
    return "the relay address starts with wss:// (or ws:// on a private network)";
  }
  if (url.hostname === "") {
    return "the relay address has no host";
  }
  return null;
}

export function lanAddress(
  interfaces: NodeJS.Dict<NetworkInterfaceInfo[]> = networkInterfaces(),
): string | null {
  for (const addresses of Object.values(interfaces)) {
    for (const address of addresses ?? []) {
      if (address.family === "IPv4" && !address.internal) {
        return address.address;
      }
    }
  }
  return null;
}

export function shareLaunch(
  choice: ShareChoice,
  args: string[],
  port: number,
  lan: string | null,
): ShareLaunch {
  if (choice.share === "local" || args.some((arg) => ADDRESS_FLAGS.includes(arg))) {
    return { args, note: null };
  }
  if (choice.share === "relay") {
    const problem = choice.relayUrl === "" ? "no relay address is set" : relayProblem(choice.relayUrl);
    return problem === null
      ? { args: [...args, "--relay", choice.relayUrl.trim()], note: null }
      : { args, note: `sharing over the internet is off: ${problem}. Open the settings (F2) → Session.` };
  }
  if (lan === null) {
    return { args, note: "sharing on the network is off: no network address was found." };
  }
  return {
    args: [...args, "--bind", "0.0.0.0", "--port", String(port), "--public-url", `ws://${lan}:${port}`],
    note: null,
  };
}
