import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { emptyState } from "@plural/client";
import { AccessCard } from "./AccessCard";
import { inboxItems } from "./items";

const request = { participant_id: "p_cleo", name: "Cleo", note: "I can fix the login test", requested_at: new Date().toISOString() };

test("the card names the person, shows the note and offers two answers", () => {
  const html = renderToStaticMarkup(<AccessCard request={request} send={() => undefined} />);
  expect(html).toContain("Cleo");
  expect(html).toContain("wants to write");
  expect(html).toContain("I can fix the login test");
  for (const answer of ["let them write", "not now"]) {
    expect(html).toContain(answer);
  }
});

test("a name and a note are shown as text, never as markup", () => {
  const html = renderToStaticMarkup(<AccessCard request={{ ...request, name: "<b onclick=x>", note: "<img src=x onerror=alert(1)>" }} send={() => undefined} />);
  expect(html).not.toContain("<img");
  expect(html).toContain("&lt;img");
});

test("someone asking to write waits for the host after people knocking and before approvals", () => {
  const state = emptyState();
  state.access_requests = { p_cleo: request };
  state.join_requests = { j_1: { id: "j_1", name: "Dana", client: "web", requested_at: request.requested_at } };
  expect(inboxItems(state).map((item) => item.kind)).toEqual(["join", "access"]);
});
