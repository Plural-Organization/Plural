import { describe, expect, test } from "vitest";
import { HISTORY_ROWS, historyView, jump, leave, MAX_HISTORY, newer, NOT_BROWSING, older, remember } from "../src";

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

  test("leaving the list gives back the line that was being typed", () => {
    const entries = ["c", "b", "a"];
    const back = older(entries, NOT_BROWSING, "half a sentence");
    expect(leave(back.browsing)).toEqual({ browsing: NOT_BROWSING, value: "half a sentence" });
    expect(leave(NOT_BROWSING).value).toBeNull();
  });
});

describe("picking a message from the list", () => {
  const entries = ["c", "b", "a"];

  test("jumping to a row recalls it and keeps the line that was being typed", () => {
    const step = jump(entries, NOT_BROWSING, 2, "half a sentence");
    expect(step.value).toBe("a");
    expect(step.browsing).toEqual({ position: 2, draft: "half a sentence" });
    expect(jump(entries, step.browsing, 0, "a").browsing.draft).toBe("half a sentence");
  });

  test("a row that is not in the list changes nothing", () => {
    expect(jump(entries, NOT_BROWSING, 3, "x").value).toBeNull();
    expect(jump(entries, NOT_BROWSING, -1, "x").value).toBeNull();
  });
});

describe("the list the arrows walk through", () => {
  const hundred = Array.from({ length: 100 }, (_, index) => `message ${100 - index}`);

  test("nothing is shown until the person steps back", () => {
    expect(historyView(hundred, NOT_BROWSING)).toBeNull();
    expect(historyView([], { position: 0, draft: "" })).toBeNull();
  });

  test("the newest message is 100 of 100 and every step back counts down", () => {
    const first = older(hundred, NOT_BROWSING, "");
    expect(historyView(hundred, first.browsing)).toMatchObject({ at: 100, of: 100 });
    const second = older(hundred, first.browsing, "");
    expect(historyView(hundred, second.browsing)).toMatchObject({ at: 99, of: 100 });
    let browsing = second.browsing;
    for (let index = 0; index < 98; index += 1) browsing = older(hundred, browsing, "").browsing;
    expect(historyView(hundred, browsing)).toMatchObject({ at: 1, of: 100 });
    expect(older(hundred, browsing, "").value).toBeNull();
  });

  test("the count grows again when the person steps forward", () => {
    const back = older(hundred, older(hundred, NOT_BROWSING, "").browsing, "");
    expect(historyView(hundred, newer(hundred, back.browsing).browsing)).toMatchObject({ at: 100 });
  });

  test("a few messages show around the current one, the oldest first, and the current one is marked", () => {
    const view = historyView(hundred, { position: 10, draft: "" });
    expect(view?.rows).toHaveLength(HISTORY_ROWS);
    expect(view?.rows.map((row) => row.text)).toEqual(["message 87", "message 88", "message 89", "message 90", "message 91", "message 92"]);
    expect(view?.rows.filter((row) => row.current).map((row) => row.text)).toEqual(["message 90"]);
  });

  test("a short list shows all of it and the window never runs past either end", () => {
    const few = ["c", "b", "a"];
    expect(historyView(few, { position: 1, draft: "" })?.rows.map((row) => row.text)).toEqual(["a", "b", "c"]);
    const first = historyView(hundred, { position: 0, draft: "" });
    expect(first?.rows.at(-1)?.text).toBe("message 100");
    const last = historyView(hundred, { position: 99, draft: "" });
    expect(last?.rows[0]?.text).toBe("message 1");
    expect(last?.rows.find((row) => row.current)?.text).toBe("message 1");
  });
});
