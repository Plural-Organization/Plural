import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";
import type { SavedSession } from "../lib/daemon";
import { SessionsToContinue } from "./SessionsToContinue";

const session = (over: Partial<SavedSession> = {}): SavedSession => ({
  room: "r_one1",
  title: "Login loop",
  folder: "acme-shop",
  available: true,
  prompts: 4,
  people: 3,
  team: null,
  updated_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
  running: false,
  ...over,
});

const render = (sessions: SavedSession[], opening: string | null = null) => renderToStaticMarkup(<SessionsToContinue sessions={sessions} opening={opening} onContinue={() => undefined} />);

test("a kept session shows its title, folder, prompts and when it was last used", () => {
  const html = render([session()]);
  expect(html).toContain("Login loop");
  expect(html).toContain("acme-shop");
  expect(html).toContain("4 prompts");
  expect(html).toContain("2 h ago");
  expect(html).toContain("Continue");
});

test("nothing kept, nothing shown", () => {
  expect(render([])).toBe("");
});

test("a session whose folder is gone cannot be continued and says so", () => {
  const html = render([session({ available: false })]);
  expect(html).toContain("folder is gone");
  expect(html).toContain("disabled");
});

test("one that is already running is opened, not continued", () => {
  expect(render([session({ running: true })])).toContain("Open");
});

test("only the newest few show before Show all", () => {
  const many = Array.from({ length: 5 }, (_, index) => session({ room: `r_room${index}`, title: `Session ${index}` }));
  const html = render(many);
  expect(html).toContain("Session 2");
  expect(html).not.toContain("Session 3");
  expect(html).toContain("Show all 5");
});

test("while one opens, the others wait", () => {
  const html = render([session(), session({ room: "r_two22", title: "Second" })], "r_one1");
  expect((html.match(/disabled/g) ?? []).length).toBeGreaterThanOrEqual(2);
});
