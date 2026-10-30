import { describe, expect, test } from "bun:test";
import { homedir } from "node:os";
import { join } from "node:path";
import { credentialsPath } from "../src/credentials";
import { dataDir } from "../src/paths";
import { settingsPath } from "../src/settings";

describe("the data folder", () => {
  test("it is PLURAL_DATA_DIR when set and ~/.plural otherwise", () => {
    expect(dataDir({ PLURAL_DATA_DIR: "/data/plural" })).toBe("/data/plural");
    expect(dataDir({})).toBe(join(homedir(), ".plural"));
  });

  test("every file of the interface lives in it", () => {
    const environment = { PLURAL_DATA_DIR: "/data/plural" };
    expect(settingsPath(environment)).toBe("/data/plural/tui.json");
    expect(credentialsPath(environment)).toBe("/data/plural/credentials.json");
  });
});
