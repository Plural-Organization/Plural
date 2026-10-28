import type { JoinLink } from "@plural/client";

const ROOMS_KEY = "plural.rooms";
const NAME_KEY = "plural.name";
const ROOM_LIMIT = 8;

export interface SavedRoom {
  room: string;
  url: string;
  token: string;
  name: string;
  savedAt: number;
}

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return;
  }
}

export function savedRooms(): SavedRoom[] {
  const rooms = read<unknown>(ROOMS_KEY, []);
  return Array.isArray(rooms) ? rooms.filter(isSavedRoom) : [];
}

export function rememberRoom(link: JoinLink, token: string, name: string): void {
  const others = savedRooms().filter((room) => room.room !== link.room);
  const next: SavedRoom = { room: link.room, url: link.url, token, name, savedAt: Date.now() };
  write(ROOMS_KEY, [next, ...others].slice(0, ROOM_LIMIT));
}

export function forgetRoom(room: string): void {
  write(
    ROOMS_KEY,
    savedRooms().filter((saved) => saved.room !== room),
  );
}

export function savedName(): string {
  const name = read<unknown>(NAME_KEY, "");
  return typeof name === "string" ? name : "";
}

function isSavedRoom(value: unknown): value is SavedRoom {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const room = value as Record<string, unknown>;
  return ["room", "url", "token", "name"].every((key) => typeof room[key] === "string");
}

export function rememberName(name: string): void {
  write(NAME_KEY, name);
}

export function linkOf(saved: SavedRoom): JoinLink {
  return { url: saved.url, room: saved.room, invite: null, token: saved.token };
}
