import { expect, test } from "vitest";
import { MAX_POINTS, sameLine, thin } from "./board";

test("a long line is thinned under the limit and keeps its ends", () => {
  const points = Array.from({ length: 9001 * 2 }, (_, index) => index / (9001 * 2));
  const thinned = thin(points);
  expect(thinned.length).toBeLessThanOrEqual(MAX_POINTS);
  expect(thinned.length % 2).toBe(0);
  expect(thinned.slice(0, 2)).toEqual(points.slice(0, 2));
  expect(thinned.slice(-2)).toEqual(points.slice(-2));
});

test("a short line is left alone", () => {
  expect(thin([0.1, 0.2, 0.3, 0.4])).toEqual([0.1, 0.2, 0.3, 0.4]);
});

test("the same line is recognised when it comes back from the host", () => {
  const line = { color: "#ffffff", width: 4, points: [0.1, 0.2, 0.3, 0.4] };
  expect(sameLine(line, { ...line, points: [...line.points] })).toBe(true);
  expect(sameLine(line, { ...line, width: 2 })).toBe(false);
});
