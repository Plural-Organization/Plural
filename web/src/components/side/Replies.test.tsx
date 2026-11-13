import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import { Replies } from "./Replies";

test("a guest reads when the agent answers but cannot switch it", () => {
  const html = renderToStaticMarkup(<Replies mode="mention" isHost={false} send={() => undefined} />);
  expect(html).toContain("messages that tag @plrl");
  expect(html).not.toContain("Every message");
});

test("the host gets the switch, set to the current mode", () => {
  const html = renderToStaticMarkup(<Replies mode="all" isHost send={() => undefined} />);
  expect(html).toContain("Every message");
  expect(html).toContain("/team writes to people only");
});
