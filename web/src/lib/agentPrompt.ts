const INSTALL_URL = "https://raw.githubusercontent.com/Plural-Organization/Plural/main/install.sh";

export function linkCommand(code: string): string {
  return `plural login --code ${code}`;
}

// What a person pastes into their own AI agent. Every step is spelled out here, so the agent follows what the page showed
// and nothing it fetches later.
export function agentPrompt(code: string): string {
  return [
    "Install Plural on this computer and link it to my Plural account. Do exactly these steps, show me each command before you run it, and stop and tell me if anything fails or looks different.",
    "",
    "1. Check the system with `uname -sm`. Plural runs on macOS and Linux; on Windows stop and tell me to use WSL.",
    "2. Install it into my home folder, without sudo:",
    `   curl -fsSL ${INSTALL_URL} -o /tmp/plural-install.sh`,
    "   sh /tmp/plural-install.sh",
    "3. Link this computer to my account. The code works once and expires in 10 minutes:",
    `   ${linkCommand(code)}`,
    "4. Check that it works with `plural doctor`.",
    "",
    "Do not read my files, keys or environment variables, do not use sudo, and do not run anything that is not listed here. When you are done, reply with one line: PLURAL_OK, or what went wrong.",
  ].join("\n");
}
