import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { historyView, NOT_BROWSING, older } from "@plural/client";
import { HistoryList } from "./HistoryList";

const entries = Array.from({ length: 100 }, (_, index) => `message ${100 - index}`);

test("the newest message reads 100 of 100 and the list marks the one in the box", () => {
  const view = historyView(entries, older(entries, NOT_BROWSING, "").browsing);
  expect(view).not.toBeNull();
  const html = renderToStaticMarkup(<HistoryList view={view!} onPick={() => undefined} />);
  expect(html).toContain('aria-label="Message 100 of 100"');
  expect(html).toContain("message 100");
  expect(html.match(/aria-selected="true"/g)).toHaveLength(1);
});

test("a message of several lines shows its first line and how many more there are", () => {
  const lines = ["first line\nsecond\nthird", "older"];
  const view = historyView(lines, { position: 0, draft: "" });
  const html = renderToStaticMarkup(<HistoryList view={view!} onPick={() => undefined} />);
  expect(html).toContain("first line");
  expect(html).not.toContain("second");
  expect(html).toContain("+2 lines");
});
