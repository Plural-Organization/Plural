import { chmodSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type Keys = Record<string, string>;

export function credentialsPath(environment: Record<string, string | undefined> = process.env): string {
  return join(environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural"), "credentials.json");
}

export function parseKeys(raw: unknown): Keys {
  const keys: Keys = {};
  const stored = typeof raw === "object" && raw !== null ? (raw as { keys?: unknown }).keys : undefined;
  if (typeof stored === "object" && stored !== null) {
    for (const [name, value] of Object.entries(stored)) {
      if (typeof value === "string" && value !== "") {
        keys[name] = value;
      }
    }
  }
  return keys;
}

export function loadKeys(path: string = credentialsPath()): Keys {
  try {
    return parseKeys(JSON.parse(readFileSync(path, "utf8")));
  } catch {
    return {};
  }
}

export function saveKeys(keys: Keys, path: string = credentialsPath()): boolean {
  try {
    const directory = dirname(path);
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    const temporary = `${path}.tmp`;
    writeFileSync(temporary, `${JSON.stringify({ keys }, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
    chmodSync(temporary, 0o600);
    renameSync(temporary, path);
    return true;
  } catch {
    return false;
  }
}
