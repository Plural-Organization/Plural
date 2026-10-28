import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { FeedItem } from "@plural/client";
import { Feed } from "./Feed";

const chat = (overrides: Partial<Extract<FeedItem, { kind: "chat" }>>): FeedItem => ({
  kind: "chat",
  id: "c1",
  authorId: "p_alia",
  name: "Alia",
  text: "standup in five",
  to: null,
  toName: null,
  mine: false,
  mentioned: false,
  ...overrides,
});

const render = (item: FeedItem) => renderToStaticMarkup(<Feed items={[item]} />);

test("a message for the room says who wrote it and that the agent does not see it", () => {
  const html = render(chat({}));
  expect(html).toContain("Alia to the team");
  expect(html).toContain("standup in five");
  expect(html).toContain("the agent does not see it");
  expect(html).not.toContain("private");
});

test("a private message names both sides", () => {
  expect(render(chat({ to: "p_me", toName: "vlad" }))).toContain("Alia to you");
  expect(render(chat({ to: "p_alia", toName: "Alia", mine: true, authorId: "p_me", name: "vlad" }))).toContain("to Alia");
  expect(render(chat({ to: "p_me", toName: "vlad" }))).toContain("private, the agent does not see it");
});

test("a tag is flagged and the text is not rendered as html", () => {
  const html = render(chat({ mentioned: true, text: "<img src=x onerror=alert(1)> @vlad" }));
  expect(html).toContain("mentions you");
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img");
});
