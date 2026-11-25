import { parseTeamInvite } from "@plural/client";

export function unwrapLink(raw: string): string {
  const text = raw
    .trim()
    .replace(/^plural join\s+/, "")
    .replace(/^["']|["']$/g, "");
  if (!/^https?:\/\//.test(text)) {
    return text;
  }
  try {
    return new URL(text).searchParams.get("join") ?? text;
  } catch {
    return text;
  }
}

export function hostOf(url: string): string {
  try {
    return new URL(url.replace(/^ws/, "http")).host;
  } catch {
    return url;
  }
}

export function browserJoinLink(invite: string, location: Pick<Location, "origin" | "pathname">): string {
  return `${location.origin}${location.pathname}?join=${encodeURIComponent(invite)}`;
}

// A shared target belongs to routing, not to the join form: App also needs to know about it so an
// existing team workspace opens the form instead of hiding the target behind its sessions menu.
export function sharedOnLoad(location: Pick<Location, "search" | "href">): string {
  const query = new URLSearchParams(location.search).get("join");
  if (query !== null) {
    return query;
  }
  return parseTeamInvite(location.href) === null ? "" : location.href;
}

export function blockedByMixedContent(link: string, protocol: string): boolean {
  return protocol === "https:" && link.startsWith("ws://");
}
