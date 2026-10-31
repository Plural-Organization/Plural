import { existsSync, readdirSync, statSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { homedir } from "node:os";

export interface Folder {
  path: string;
  name: string;
  detail: string;
}

function isFolder(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

export function isRepo(path: string): boolean {
  return existsSync(join(path, ".git"));
}

export function expandHome(path: string, home: string = homedir()): string {
  return path === "~" ? home : path.startsWith("~/") ? join(home, path.slice(2)) : path;
}

export function checkFolder(raw: string, base: string = process.cwd()): { path: string } | { error: string } {
  const text = raw.trim();
  if (text === "") {
    return { error: "type a folder path" };
  }
  const path = resolve(base, expandHome(text));
  return isFolder(path) ? { path } : { error: `${path} is not a folder` };
}

function describe(path: string): string {
  return `${isRepo(path) ? "git repo · " : ""}${path}`;
}

/** The folders worth offering: here, where earlier sessions ran, and repositories next to here. */
export function candidateFolders(cwd: string, recent: readonly string[] = [], limit = 12): Folder[] {
  const seen = new Set<string>();
  const found: Folder[] = [];
  const add = (path: string): void => {
    if (found.length >= limit || seen.has(path) || !isFolder(path)) {
      return;
    }
    seen.add(path);
    found.push({ path, name: basename(path) || path, detail: describe(path) });
  };
  add(cwd);
  for (const path of recent) {
    add(path);
  }
  const parent = dirname(cwd);
  try {
    for (const entry of readdirSync(parent, { withFileTypes: true })) {
      const path = join(parent, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith(".") && isRepo(path)) {
        add(path);
      }
    }
  } catch {
    return found;
  }
  return found;
}
