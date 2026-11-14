import { describe, expect, test } from "vitest";
import { MAX_HISTORY, newer, NOT_BROWSING, older, remember } from "./promptHistory";

describe("prompt history", () => {
  test("the newest message comes first, a repeat moves up instead of doubling, a blank one is not kept", () => {
    let entries: string[] = [];
    for (const text of ["one", "two", "one", "  ", ""]) entries = remember(entries, text);
    expect(entries).toEqual(["one", "two"]);
  });

  test("it keeps the last hundred", () => {
    let entries: string[] = [];
    for (let index = 0; index < 130; index += 1) entries = remember(entries, `message ${index}`);
    expect(entries).toHaveLength(MAX_HISTORY);
    expect(entries[0]).toBe("message 129");
    expect(entries.at(-1)).toBe("message 30");
  });

  test("up walks back to older messages and stops at the oldest", () => {
    const entries = ["c", "b", "a"];
    const first = older(entries, NOT_BROWSING, "draft");
    expect(first.value).toBe("c");
    const second = older(entries, first.browsing, "c");
    const third = older(entries, second.browsing, "b");
    expect(third.value).toBe("a");
    expect(older(entries, third.browsing, "a").value).toBeNull();
  });

  test("down walks forward and past the newest message gives back the line that was being typed", () => {
    const entries = ["c", "b", "a"];
    const back = older(entries, older(entries, NOT_BROWSING, "half a sentence").browsing, "c");
    expect(back.value).toBe("b");
    const forward = newer(entries, back.browsing);
    expect(forward.value).toBe("c");
    const done = newer(entries, forward.browsing);
    expect(done.value).toBe("half a sentence");
    expect(newer(entries, done.browsing).value).toBeNull();
  });

  test("with nothing sent yet, up changes nothing", () => {
    expect(older([], NOT_BROWSING, "").value).toBeNull();
  });
});
