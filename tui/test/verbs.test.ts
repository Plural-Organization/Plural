import { expect, test } from "bun:test";
import { doneText, firstVerb, took, VERB_MS, verbAt, VERBS } from "../src/verbs";

test("the verb moves on every few seconds and wraps around", () => {
  expect(verbAt(0, 0)).toBe(0);
  expect(verbAt(0, VERB_MS)).toBe(1);
  expect(verbAt(VERBS.length - 1, VERB_MS)).toBe(0);
  expect(firstVerb(() => 0.999)).toBe(VERBS.length - 1);
});

test("a run's length reads in seconds, then minutes", () => {
  expect(took(14_200)).toBe("14s");
  expect(took(125_000)).toBe("2m 5s");
});

test("the summary names the past form of the verb and the clock", () => {
  expect(doneText(0, 3_000, new Date(2026, 10, 1, 14, 27))).toMatch(/^Cogitated for 3s · done .*27/);
});
