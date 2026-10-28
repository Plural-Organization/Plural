import * as childProcess from "node:child_process";

/** Use the macOS alert sound independently of the terminal's audible-bell setting. */
export function ring(): void {
  if (process.platform === "darwin" && process.stdout.isTTY) {
    const child = childProcess.spawn("osascript", ["-e", "beep 1"], { stdio: "ignore" });
    child.on("error", () => undefined);
    child.unref();
    return;
  }
  process.stdout.write("\u0007");
}
