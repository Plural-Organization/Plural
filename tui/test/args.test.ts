import { describe, expect, test } from "bun:test";
import { fixDashes } from "../src/args";

describe("dashes typed by a keyboard or a chat", () => {
  test("a long dash before an option name becomes two hyphens", () => {
    expect(fixDashes(["—tunnel", "cloudflared"])).toEqual(["--tunnel", "cloudflared"]);
    expect(fixDashes(["–relay", "wss://r.example.com", "—name", "vlad"])).toEqual([
      "--relay",
      "wss://r.example.com",
      "--name",
      "vlad",
    ]);
  });

  test("a single short option keeps one hyphen", () => {
    expect(fixDashes(["–v"])).toEqual(["-v"]);
  });

  test("ordinary arguments and values are left alone", () => {
    const args = ["join", "wss://r.example.com/r_1?invite=a", "--name", "alia", "-v", "—", "a—b", "2026—10"];
    expect(fixDashes(args)).toEqual(args);
  });
});
