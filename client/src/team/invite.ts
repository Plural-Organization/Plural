import type { TeamInvite, TeamProfile } from "./types";

// The relay a pasted command names: `--relay <url>`, `--relay=<url>` or `--relay = <url>`.
// This reads words instead of matching one regular expression: `--relay[\s=]+(\S+)` overlaps on "=" and
// backtracks badly on a long run of them (CodeQL js/polynomial-redos), and this text is pasted by anyone.
function relayOf(words: string[]): string | null {
  const flag = words.findIndex((word) => word === "--relay" || word.startsWith("--relay="));
  if (flag === -1) {
    return null;
  }
  const value = (word: string): string => word.replace(/^=+/, "");
  const inline = value((words[flag] as string).slice("--relay".length));
  if (inline !== "") {
    return inline;
  }
  // A lone "=" is a separator, so the address is the next word that is more than that.
  for (let index = flag + 1; index < words.length; index += 1) {
    const next = value(words[index] as string);
    if (next !== "") {
      return next;
    }
  }
  return null;
}

function parseCommand(text: string): TeamInvite | null {
  const words = text.split(/\s+/);
  const join = words.findIndex((word, index) => word === "team" && words[index + 1] === "join");
  const code = join === -1 ? undefined : words[join + 2];
  const relay = relayOf(words);
  return code !== undefined && !code.startsWith("-") && relay !== null ? { code, relay } : null;
}

// What a teammate pastes: the command `plural team join <code> --relay <url>`, or the web client's link
// with ?team=<code>&relay=<url>.
export function parseTeamInvite(text: string): TeamInvite | null {
  const trimmed = text.trim();
  const command = parseCommand(trimmed);
  if (command) {
    return command;
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
