import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export interface JoinedRoom {
  room: string;
  url: string;
  token: string;
  name: string;
  savedAt: string;
}

const LIMIT = 20;

export function joinedPath(environment: Record<string, string | undefined> = process.env): string {
  return join(environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural"), "joined.json");
}

export function loadJoined(path: string = joinedPath()): JoinedRoom[] {
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw.filter(
      (entry): entry is JoinedRoom =>
        typeof entry === "object" && entry !== null && ["room", "url", "token", "name", "savedAt"].every((key) => typeof (entry as Record<string, unknown>)[key] === "string"),
    );
  } catch {
    return [];
  }
}

function save(rooms: JoinedRoom[], path: string): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(rooms, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(temporary, 0o600);
  renameSync(temporary, path);
}

export function rememberJoined(entry: Omit<JoinedRoom, "savedAt">, path: string = joinedPath(), now: Date = new Date()): void {
  const others = loadJoined(path).filter((room) => room.room !== entry.room);
  save([{ ...entry, savedAt: now.toISOString() }, ...others].slice(0, LIMIT), path);
}

export function forgetJoined(room: string, path: string = joinedPath()): void {
  save(loadJoined(path).filter((entry) => entry.room !== room), path);
}

export function rejoinLink(entry: JoinedRoom): string {
  return `${entry.url}?token=${entry.token}`;
}
