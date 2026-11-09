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

test("agent mentions highlight session members but leave code, emails and unknown names alone", () => {
  const text = "@synapse, **@SYNAPSE** and `@synapse`; email x@synapse; @stranger.";
  const html = renderToStaticMarkup(<Feed people={[{ id: "p_s", label: "synapse", role: "host", connected: true }]} items={[{ kind: "assistant", id: "a1", text, streaming: false } as FeedItem]} />);
  expect(html.match(/data-mention="p_s"/g)).toHaveLength(2);
  expect(html).toContain("<code>@synapse</code>");
  expect(html).toContain("x@synapse");
  expect(html).toContain("@stranger");
});

test("people's messages highlight the members they name too", () => {
  const html = renderToStaticMarkup(<Feed people={[{ id: "p_v", label: "vlad", role: "participant", connected: true }]} items={[chat({ text: "@vlad look, @nobody" })]} />);
  expect(html.match(/data-mention="p_v"/g)).toHaveLength(1);
  expect(html).toContain("@nobody");
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
