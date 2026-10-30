import { homedir } from "node:os";
import { join } from "node:path";

export function dataDir(environment: Record<string, string | undefined> = process.env): string {
  return environment["PLURAL_DATA_DIR"] ?? join(homedir(), ".plural");
}
