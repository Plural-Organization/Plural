import { afterAll, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { MAX_HISTORY } from "@plural/client";
import { historyPath, loadHistory, saveHistory } from "../src/history";

const dir = mkdtempSync(join(tmpdir(), "plural-history-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

describe("the prompt history on disk", () => {
  test("it lives in the data directory", () => {
    expect(historyPath({ PLURAL_DATA_DIR: "/data" })).toBe("/data/history.json");
  });

  test("what was saved comes back in the same order", () => {
    const path = join(dir, "roundtrip", "history.json");
    saveHistory(["newest", "middle\nwith two lines", "oldest"], path);
    expect(loadHistory(path)).toEqual(["newest", "middle\nwith two lines", "oldest"]);
  });

  test("the file is readable by its owner only", () => {
    const path = join(dir, "private.json");
    saveHistory(["a prompt can hold anything"], path);
    expect(statSync(path).mode & 0o777).toBe(0o600);
  });

  test("it keeps the last hundred", () => {
    const path = join(dir, "cap.json");
    saveHistory(Array.from({ length: 130 }, (_, index) => `prompt ${index}`), path);
    const saved = loadHistory(path);
    expect(saved).toHaveLength(MAX_HISTORY);
    expect(saved[0]).toBe("prompt 0");
  });

  test("a pasted file is too long to keep on disk but does not drop the others", () => {
    const path = join(dir, "long.json");
    saveHistory(["short", "x".repeat(20_000), "also short"], path);
    expect(loadHistory(path)).toEqual(["short", "also short"]);
  });

  test("a missing, broken or foreign file reads as an empty history", () => {
    expect(loadHistory(join(dir, "missing.json"))).toEqual([]);
    const broken = join(dir, "broken.json");
    writeFileSync(broken, "{not json");
    expect(loadHistory(broken)).toEqual([]);
    const foreign = join(dir, "foreign.json");
    writeFileSync(foreign, JSON.stringify({ a: 1 }));
    expect(loadHistory(foreign)).toEqual([]);
    const mixed = join(dir, "mixed.json");
    writeFileSync(mixed, JSON.stringify(["ok", 3, "", null, "fine"]));
    expect(loadHistory(mixed)).toEqual(["ok", "fine"]);
  });

  test("saving leaves no temporary file behind", () => {
    const path = join(dir, "clean.json");
    saveHistory(["one"], path);
    expect(() => readFileSync(`${path}.tmp`)).toThrow();
  });
});
