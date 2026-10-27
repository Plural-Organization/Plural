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

export function blockedByMixedContent(link: string, protocol: string): boolean {
  return protocol === "https:" && link.startsWith("ws://");
}
