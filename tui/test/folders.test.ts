import { describe, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { candidateFolders, checkFolder, expandHome, isRepo } from "../src/folders";

function workspace(): string {
  return mkdtempSync(join(tmpdir(), "plural-folders-"));
}

describe("folders to share", () => {
  test("offers here first, then repositories next to it, without duplicates", () => {
    const root = workspace();
    for (const name of ["api", "web", "notes"]) {
      mkdirSync(join(root, name));
    }
    mkdirSync(join(root, "api", ".git"));
    mkdirSync(join(root, "web", ".git"));
    const found = candidateFolders(join(root, "api"), [join(root, "api")]);
    expect(found.map((folder) => folder.name)).toEqual(["api", "web"]);
    expect(found[0]?.detail).toContain("git repo");
  });

  test("skips recent folders that are gone", () => {
    const root = workspace();
    mkdirSync(join(root, "here"));
    const found = candidateFolders(join(root, "here"), [join(root, "gone")]);
    expect(found.map((folder) => folder.name)).toEqual(["here"]);
  });

  test("a typed path must be an existing folder", () => {
    const root = workspace();
    writeFileSync(join(root, "file.txt"), "x");
    mkdirSync(join(root, "app"));
    expect(checkFolder("app", root)).toEqual({ path: join(root, "app") });
    expect(checkFolder("file.txt", root)).toHaveProperty("error");
    expect(checkFolder("  ", root)).toHaveProperty("error");
    expect(isRepo(root)).toBe(false);
  });

  test("~ means the home folder", () => {
    expect(expandHome("~/code", "/home/vlad")).toBe("/home/vlad/code");
    expect(expandHome("~", "/home/vlad")).toBe("/home/vlad");
    expect(expandHome("/tmp/x", "/home/vlad")).toBe("/tmp/x");
  });
});
