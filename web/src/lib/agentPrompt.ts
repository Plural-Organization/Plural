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

export const DAEMON_PORT = 47831;

// What a person pastes into their AI agent to get a computer ready to start rooms from the page: install, sign in,
// and keep the daemon running. The agent is told not to ask; the two things only the person can do are named.
export function daemonPrompt(): string {
  return [
    "Set up Plural on this computer so I can start rooms from the Plural website. Run the steps yourself without asking me questions. Stop only if a step fails, or when a step needs me (marked below).",
    "",
    "1. Check the system with `uname -sm`. Plural runs on macOS and Linux; on Windows stop and tell me to use WSL.",
    "2. Install it into my home folder, without sudo:",
    `   curl -fsSL ${INSTALL_URL} -o /tmp/plural-install.sh`,
    "   sh /tmp/plural-install.sh",
    "3. Sign in. This opens my browser and I approve it there (needs me). Wait until it prints \"Linked to\":",
    "   plural login",
    "4. Start the daemon in the background so it keeps running after you finish:",
    "   nohup plural daemon > /tmp/plural-daemon.log 2>&1 &",
    `5. Check it answers: curl -s http://127.0.0.1:${DAEMON_PORT}/v1/status`,
    "",
    "Then tell me to go back to the Plural page and press Allow when my browser asks to access the local network (needs me).",
    "Do not read my files, keys or environment variables, do not use sudo, and do not run anything that is not listed here. When you are done, reply with one line: PLURAL_OK, or what went wrong.",
  ].join("\n");
}

// The same three steps for someone who runs them by hand, as one block to copy.
export function manualSteps(): string {
  return [`curl -fsSL ${INSTALL_URL} | sh`, "plural login", "plural daemon"].join("\n");
}
