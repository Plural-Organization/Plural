import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const NATIVE: Record<string, string[]> = {
  darwin: ["pbcopy"],
  linux: ["wl-copy"],
};

function native(text: string): Promise<boolean> {
  const command = NATIVE[process.platform];
  if (!command) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const child = spawn(command[0] as string, command.slice(1), { stdio: ["pipe", "ignore", "ignore"] });
    child.on("error", () => resolve(false));
    child.on("close", (code) => resolve(code === 0));
    child.stdin.end(text);
  });
}

export async function copyToClipboard(text: string, osc52: (text: string) => void): Promise<void> {
  if (await native(text)) {
    return;
  }
  osc52(text);
}

const LONG_EDGE = 1568;
export const IMAGE_LIMIT_BYTES = 2_500_000;

function run(command: string, args: string[]): Promise<Buffer | null> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "ignore"] });
    const chunks: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));
    child.on("error", () => resolve(null));
    child.on("close", (code) => resolve(code === 0 ? Buffer.concat(chunks) : null));
  });
}

async function macImage(): Promise<Buffer | null> {
  const dir = await mkdtemp(join(tmpdir(), "plural-paste-"));
  const png = join(dir, "paste.png");
  try {
    const saved = await run("osascript", [
      "-e", "set png to (the clipboard as «class PNGf»)",
      "-e", `set out to open for access POSIX file "${png}" with write permission`,
      "-e", "write png to out",
      "-e", "close access out",
    ]);
    if (saved === null) {
      return null;
    }
    // Models scale anything larger down to this edge anyway, so a smaller upload costs nothing.
    await run("sips", ["-Z", String(LONG_EDGE), png]);
    const data = await readFile(png);
    if (data.length <= IMAGE_LIMIT_BYTES) {
      return data;
    }
    const jpeg = join(dir, "paste.jpg");
    await run("sips", ["-s", "format", "jpeg", "-s", "formatOptions", "80", png, "--out", jpeg]);
    return await readFile(jpeg).catch(() => data);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function linuxImage(): Promise<Buffer | null> {
  const wayland = await run("wl-paste", ["--no-newline", "--type", "image/png"]);
  if (wayland !== null && wayland.length > 0) {
    return wayland;
  }
  const x11 = await run("xclip", ["-selection", "clipboard", "-target", "image/png", "-out"]);
  return x11 !== null && x11.length > 0 ? x11 : null;
}

/** The image on the system clipboard, or null when it holds none or the platform has no way to read it. */
export async function pasteImage(): Promise<Buffer | null> {
  if (process.platform === "darwin") {
    return macImage();
  }
  if (process.platform === "linux") {
    return linuxImage();
  }
  return null;
}

