import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { emptyState } from "@plural/client";
import { BriefingAsk } from "./BriefingAsk";
import { inboxItems } from "./items";

const request = { id: "b_1", participant_id: "p_cleo", name: "Cleo", focus: "how was login fixed?", update: false, requested_at: new Date().toISOString() };

test("the card names who asks, what about, and offers two answers", () => {
  const html = renderToStaticMarkup(<BriefingAsk request={request} send={() => undefined} />);
  expect(html).toContain("Cleo");
  expect(html).toContain("how was login fixed?");
  for (const answer of ["write it", "not now"]) {
    expect(html).toContain(answer);
  }
  expect(renderToStaticMarkup(<BriefingAsk request={{ ...request, update: true }} send={() => undefined} />)).toContain("an update");
});

test("a name and a question are shown as text, never as markup", () => {
  const html = renderToStaticMarkup(<BriefingAsk request={{ ...request, name: "<b>x</b>", focus: "<img src=x onerror=alert(1)>" }} send={() => undefined} />);
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img");
});

test("a request for a briefing waits for the host among the other things", () => {
  const state = emptyState();
  state.briefing_requests = { b_1: request };
  state.access_requests = { p_cleo: { participant_id: "p_cleo", name: "Cleo", note: null, requested_at: request.requested_at } };
  expect(inboxItems(state).map((item) => item.kind)).toEqual(["access", "briefing"]);
});
