import { expect, spyOn, test } from "bun:test";
import * as childProcess from "node:child_process";
import { EventEmitter } from "node:events";
import { ring } from "../src/lib/sound";

test("macOS uses native audio without emitting the terminal bell", () => {
  if (process.platform !== "darwin") return;
  const descriptor = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
  const child = Object.assign(new EventEmitter(), { unref: () => undefined });
  const spawn = spyOn(childProcess, "spawn").mockReturnValue(child as childProcess.ChildProcess);
  const write = spyOn(process.stdout, "write");
  try {
    Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });
    ring();
    expect(spawn).toHaveBeenCalledWith("osascript", ["-e", "beep 1"], { stdio: "ignore" });
    expect(write.mock.calls.filter(([chunk]) => chunk === "\u0007")).toHaveLength(0);
    expect(() => child.emit("error", new Error("audio unavailable"))).not.toThrow();
  } finally {
    spawn.mockRestore();
    write.mockRestore();
    if (descriptor) Object.defineProperty(process.stdout, "isTTY", descriptor);
    else Reflect.deleteProperty(process.stdout, "isTTY");
  }
});
