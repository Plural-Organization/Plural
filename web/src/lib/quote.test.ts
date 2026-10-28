import { expect, test } from "vitest";
import { asQuote, segments, withQuote } from "./quote";

test("a selection becomes a markdown quote with blank lines kept", () => {
  expect(asQuote("  first\n\nsecond  ")).toBe("> first\n>\n> second");
});

test("a quote goes after what is typed and leaves room to answer", () => {
  expect(withQuote("", "hi")).toBe("> hi\n\n");
  expect(withQuote("look:  ", "hi")).toBe("look:\n\n> hi\n\n");
});

test("a message splits into the quote and the answer", () => {
  expect(segments("> first\n>\n> second\n\nmy answer")).toEqual([
    { quote: true, text: "first\n\nsecond" },
    { quote: false, text: "my answer" },
  ]);
  expect(segments("no quote here")).toEqual([{ quote: false, text: "no quote here" }]);
  expect(segments("> only a quote")).toEqual([{ quote: true, text: "only a quote" }]);
  expect(segments(">\n> a")).toEqual([{ quote: true, text: "a" }]);
  expect(segments(">\n>")).toEqual([]);
  expect(segments(">not a quote")).toEqual([{ quote: false, text: ">not a quote" }]);
});
