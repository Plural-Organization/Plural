import type { TeamInvite, TeamProfile } from "./types";

// What a teammate pastes: the command `plural team join <code> --relay <url>`, or the web client's link
// with ?team=<code>&relay=<url>.
export function parseTeamInvite(text: string): TeamInvite | null {
  const trimmed = text.trim();
  const command = /team\s+join\s+(\S+)\s+--relay[\s=]+(\S+)/.exec(trimmed) ?? /--relay[\s=]+(\S+)\s.*?team\s+join\s+(\S+)/.exec(trimmed);
  if (command) {
    const [code, relay] = command[0].startsWith("--relay") ? [command[2]!, command[1]!] : [command[1]!, command[2]!];
    return { code, relay };
  }
  try {
    const url = new URL(trimmed);
    const code = url.searchParams.get("team");
    const relay = url.searchParams.get("relay");
    return code && relay ? { code, relay } : null;
  } catch {
    return null;
  }
}

export function teamJoinCommand(profile: TeamProfile, code: string): string {
  return `plural team join ${code} --relay ${profile.relay}`;
}

export function teamJoinLink(profile: TeamProfile, code: string, location: { origin: string; pathname: string }): string {
  return `${location.origin}${location.pathname}?team=${encodeURIComponent(code)}&relay=${encodeURIComponent(profile.relay)}`;
}
