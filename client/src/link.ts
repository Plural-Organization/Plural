export interface JoinLink {
  url: string;
  room: string;
  invite: string | null;
  token: string | null;
  join: string | null;
}

export function parseLink(raw: string): JoinLink {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("link must start with ws:// or wss://");
  }
  if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
    throw new Error("link must start with ws:// or wss://");
  }
  const room = parsed.pathname.replace(/\/+$/, "").split("/").pop() ?? "";
  if (room === "") {
    throw new Error("link has no room");
  }
  return {
    url: `${parsed.protocol}//${parsed.host}${parsed.pathname}`,
    room,
    invite: parsed.searchParams.get("invite"),
    token: parsed.searchParams.get("token"),
    join: parsed.searchParams.get("join"),
  };
}
