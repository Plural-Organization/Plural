import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";
import { App } from "../src/App";
import { demoSession } from "./scene";

const fake = demoSession();

const renderer = await createCliRenderer({ exitOnCtrlC: false, useMouse: true });
createRoot(renderer).render(
  <App client={fake} room="r_01M5W7ACDDJR7954MF354JW85W" version="0.2.0" guestLink="ws://127.0.0.1:7777/r_01M5W7ACDDJR7954MF354JW85W?invite=abc" onQuit={() => renderer.destroy()} />,
);
