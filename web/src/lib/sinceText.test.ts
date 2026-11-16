import { expect, test } from "vitest";
import { sinceText } from "./sinceText";

const NOW = Date.parse("2026-11-16T12:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();

test("a session says when it was last used, in the largest sensible unit", () => {
  expect(sinceText(ago(20_000), NOW)).toBe("just now");
  expect(sinceText(ago(5 * 60_000), NOW)).toBe("5 min ago");
  expect(sinceText(ago(3 * 3_600_000), NOW)).toBe("3 h ago");
  expect(sinceText(ago(24 * 3_600_000), NOW)).toBe("yesterday");
  expect(sinceText(ago(4 * 86_400_000), NOW)).toBe("4 days ago");
});

test("a date that cannot be read says nothing, and one in the future is just now", () => {
  expect(sinceText("not a date", NOW)).toBe("");
  expect(sinceText(new Date(NOW + 60_000).toISOString(), NOW)).toBe("just now");
});
