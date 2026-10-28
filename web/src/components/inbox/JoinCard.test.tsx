import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { emptyState } from "@plural/client";
import { JoinCard } from "./JoinCard";
import { inboxItems } from "./items";

const request = { id: "j_1", name: "Dana", client: "web 0.2.2", requested_at: new Date().toISOString() };

test("the card names the person and offers the three answers", () => {
  const html = renderToStaticMarkup(<JoinCard request={request} send={() => undefined} />);
  expect(html).toContain("Dana");
  expect(html).toContain("wants to join");
  expect(html).toContain("web 0.2.2");
  for (const answer of ["let in", "as a viewer", "refuse"]) {
    expect(html).toContain(answer);
  }
});

test("a name is shown as text, never as markup", () => {
  const html = renderToStaticMarkup(<JoinCard request={{ ...request, name: "<img src=x onerror=alert(1)>" }} send={() => undefined} />);
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img");
});

test("people who wait come first in what waits for the host", () => {
  const state = emptyState();
  state.join_requests = { j_1: request };
  state.proposals = { pr_1: { id: "pr_1", author_id: "p_a", text: "x", delivery: "now", attachments: [] } };
  expect(inboxItems(state).map((item) => item.kind)).toEqual(["join", "proposal"]);
});
