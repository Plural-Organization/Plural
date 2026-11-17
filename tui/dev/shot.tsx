// Draws the demo conversation off-screen and writes it as an HTML page:
// bun dev/shot.tsx out.html [width] [height] [theme] [keys], where keys is text to type, "esc", "tab", "f2" or "enter", separated by commas.
import { testRender } from "@opentui/react/test-utils";
import { App } from "../src/App";
import { DEFAULT_SETTINGS } from "../src/settings";
import type { ThemeName } from "../src/theme";
import { demoSession } from "./scene";

const [out = "shot.html", width = "140", height = "46", themeName, keys = "", team = "0"] = process.argv.slice(2);
const people = ["vlad", "alia", "bek", "cleo", "dan", "erin", "farid", "gleb", "hana", "ivan", "jun", "kira"];
const spaces = people.slice(0, Number(team)).map((name, index) => ({
  id: index === 0 ? "own" : `r_${name}`,
  title: name,
  detail: `plural · ${["main", "feat/login", "fix/relay", "feat/tui"][index % 4]}`,
  status: (["running", "waiting", "idle"] as const)[index % 3]!,
  viewers: index % 4 === 1 ? 2 : 0,
  mine: index === 0,
  active: index === 0,
  offline: false,
  clash: index === 2,
  warning: null,
}));
const settings = { ...DEFAULT_SETTINGS, setupSeen: true, ...(themeName && themeName !== "-" ? { theme: themeName as ThemeName } : {}) };
const setup = await testRender(
  <App client={demoSession()} room="r_01M5W7ACDDJR7954MF354JW85W" version="0.2.0" guestLink="ws://127.0.0.1:7777/r_01M5W7ACDDJR7954MF354JW85W?invite=abc" settings={settings} {...(spaces.length > 0 ? { spaces, teamName: "Backend" } : {})} onQuit={() => undefined} />,
  { width: Number(width), height: Number(height) },
);
const pause = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 400));
await pause();
for (const key of keys.split(",").filter(Boolean)) {
  await setup.renderOnce();
  if (key === "esc") {
    setup.mockInput.pressEscape();
  } else if (key === "tab") {
    setup.mockInput.pressTab();
  } else if (key === "enter") {
    setup.mockInput.pressEnter();
  } else if (key === "f2") {
    setup.mockInput.pressKey("F2");
  } else {
    await setup.mockInput.typeText(key);
  }
  await pause();
}
await setup.renderOnce();
const css = (color: { toInts: () => number[] }): string => {
  const [r, g, b, a] = color.toInts();
  return a === 0 ? "transparent" : `rgb(${r},${g},${b})`;
};
const escape = (text: string): string => text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const lines = setup.captureSpans().lines.map((line) =>
  line.spans
    .map((span) => `<span style="color:${css(span.fg)};background:${css(span.bg)};${span.attributes & 1 ? "font-weight:700;" : ""}${span.attributes & 4 ? "font-style:italic;" : ""}">${escape(span.text)}</span>`)
    .join(""),
);
await Bun.write(out, `<meta charset="utf-8"><style>span{display:inline-block;height:17.5px;vertical-align:top}</style><body style="margin:0;background:#000"><pre style="margin:0;font:14px/17.5px Menlo,monospace;display:inline-block">${lines.join("\n")}</pre>`);
setup.renderer.destroy();
process.exit(0);
