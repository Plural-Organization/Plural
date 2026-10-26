import { spawn } from "node:child_process";

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
