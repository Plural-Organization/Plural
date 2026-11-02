import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { PluginAsked } from "@plural/client";
import { askItems } from "./items";
import { PluginAskCard } from "./PluginAskCard";

const ask: PluginAsked = { type: "plugin.asked", ask_id: "pq1", command: "deploy", kind: "select", title: "where to?", options: ["staging", "prod"], default: "" };

test("a plugin's question shows its options, a way to close it, and that only you see it", () => {
  const html = renderToStaticMarkup(<PluginAskCard ask={ask} answer={() => undefined} />);
  for (const text of ["/deploy", "where to?", "staging", "prod", "close", "only you see this"]) {
    expect(html).toContain(text);
  }
  const confirm = renderToStaticMarkup(<PluginAskCard ask={{ ...ask, kind: "confirm", options: [] }} answer={() => undefined} />);
  expect(confirm).toContain("yes");
  const input = renderToStaticMarkup(<PluginAskCard ask={{ ...ask, kind: "input", default: "v1" }} answer={() => undefined} />);
  expect(input).toContain('value="v1"');
});

test("a plugin's title is text, never markup", () => {
  const html = renderToStaticMarkup(<PluginAskCard ask={{ ...ask, title: "<img src=x onerror=alert(1)>" }} answer={() => undefined} />);
  expect(html).not.toContain("<img");
});

test("questions come first in the inbox, oldest first", () => {
  expect(askItems([ask, { ...ask, ask_id: "pq2" }]).map((item) => item.id)).toEqual(["pq1", "pq2"]);
});
