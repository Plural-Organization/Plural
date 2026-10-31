export class UsageError extends Error {}

export type Resume = { kind: "pick" } | { kind: "continue" } | { kind: "id"; value: string };
export type OutputFormat = "text" | "json" | "stream-json";

export interface SessionOptions {
  hostArgs: string[];
  tunnel: string | null;
  resume: Resume | null;
  print: boolean;
  prompt: string | null;
  outputFormat: OutputFormat;
  model: string | null;
  provider: string | null;
  effort: string | null;
  permissionMode: string | null;
  allowedTools: string[];
  disallowedTools: string[];
  displayName: string | null;
}

export type Parsed =
  | { kind: "version" }
  | { kind: "help" }
  | { kind: "selftest" }
  | { kind: "update"; check: boolean }
  | { kind: "passthrough"; args: string[] }
  | { kind: "join"; link: string | null; displayName: string | null }
  | { kind: "team_host"; name: string; tunnel: string; member: string | null }
  | { kind: "team_join"; args: string[] }
  | { kind: "session"; options: SessionOptions };

const PASSTHROUGH = new Set(["relay", "doctor", "export", "sessions", "rm", "team", "ls"]);

const HOST_VALUES: Record<string, string> = {
  "--workspace": "--workspace",
  "--prompts": "--prompts",
  "--port": "--port",
  "--bind": "--bind",
  "--relay": "--relay",
  "--public-url": "--public-url",
  "--room": "--room",
  "--title": "--title",
  "-n": "--title",
};

const FORMATS: readonly OutputFormat[] = ["text", "json", "stream-json"];
const EFFORTS = ["low", "medium", "high", "xhigh", "max"];
const MODES: Record<string, string> = {
  default: "default",
  acceptedits: "accept_edits",
  accept_edits: "accept_edits",
  "accept-edits": "accept_edits",
  plan: "plan",
  auto: "auto",
};

export function permissionModeOf(value: string): string {
  const mode = MODES[value.toLowerCase()];
  if (mode === undefined) {
    throw new UsageError("--permission-mode takes default, acceptEdits, plan or auto");
  }
  return mode;
}

function list(value: string): string[] {
  const items: string[] = [];
  let depth = 0;
  let current = "";
  for (const char of value) {
    if (char === "(") depth += 1;
    if (char === ")") depth = Math.max(0, depth - 1);
    if ((char === "," || /\s/.test(char)) && depth === 0) {
      if (current !== "") items.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  if (current !== "") items.push(current);
  return items;
}

export function emptyOptions(): SessionOptions {
  return {
    hostArgs: [],
    tunnel: null,
    resume: null,
    print: false,
    prompt: null,
    outputFormat: "text",
    model: null,
    provider: null,
    effort: null,
    permissionMode: null,
    allowedTools: [],
    disallowedTools: [],
    displayName: null,
  };
}

function expand(argv: string[]): string[] {
  return argv.flatMap((arg) => {
    const match = /^(--[a-zA-Z][\w-]*)=(.*)$/s.exec(arg);
    return match === null ? [arg] : [match[1] as string, match[2] as string];
  });
}

export function parseArgs(input: string[]): Parsed {
  const argv = expand(input);
  const [first, ...rest] = argv;
  if (first === "--version" || first === "-v") return { kind: "version" };
  if (first === "--selftest") return { kind: "selftest" };
  if (first === "--help" || first === "-h") return { kind: "help" };
  if (first === "team" && rest[0] === "create" && rest.includes("--tunnel")) return teamHost(rest.slice(1));
  if (first === "team" && rest[0] === "join") return { kind: "team_join", args: argv };
  if (first !== undefined && PASSTHROUGH.has(first)) return { kind: "passthrough", args: argv };
  if (first === "update") return update(rest);
  if (first === "join") return join(rest);
  return { kind: "session", options: session(first === "host" ? rest : argv) };
}

function update(args: string[]): Parsed {
  let check = false;
  for (const arg of args) {
    if (arg === "--check") {
      check = true;
    } else {
      throw new UsageError(`unknown argument ${arg} for plural update. plural update [--check]`);
    }
  }
  return { kind: "update", check };
}

function join(args: string[]): Parsed {
  let link: string | null = null;
  let displayName: string | null = null;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index] as string;
    if (arg === "--name") {
      displayName = valueOf(args, index, arg);
      index += 1;
    } else if (arg.startsWith("-")) {
      throw new UsageError(`unknown option ${arg} for plural join`);
    } else if (link === null) {
      link = arg;
    } else {
      throw new UsageError("usage: plural join <link|@name> [--name <name>]");
    }
  }
  return { kind: "join", link, displayName };
}

function teamHost(args: string[]): Parsed {
  const usage = "usage: plural team create <name> --tunnel cloudflared|ngrok [--as <name>]";
  let name: string | null = null;
  let tunnel: string | null = null;
  let member: string | null = null;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index] as string;
    if (arg === "--tunnel") {
      tunnel = valueOf(args, index, arg);
      index += 1;
    } else if (arg === "--as") {
      member = valueOf(args, index, arg);
      index += 1;
    } else if (arg === "--relay") {
      throw new UsageError("--tunnel starts the team's relay itself, drop --relay");
    } else if (arg.startsWith("-")) {
      throw new UsageError(`unknown option ${arg} for plural team create. ${usage}`);
    } else if (name === null) {
      name = arg;
    } else {
      throw new UsageError(usage);
    }
  }
  if (name === null || tunnel === null) {
    throw new UsageError(usage);
  }
  return { kind: "team_host", name, tunnel, member };
}

function valueOf(args: string[], index: number, name: string): string {
  const value = args[index + 1];
  if (value === undefined || (value.startsWith("-") && value.length > 1)) {
    throw new UsageError(`${name} needs a value`);
  }
  return value;
}

function session(args: string[]): SessionOptions {
  const options = emptyOptions();
  const positional: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index] as string;
    const hostFlag = HOST_VALUES[arg];
    if (hostFlag !== undefined) {
      options.hostArgs.push(hostFlag, valueOf(args, index, arg));
      index += 1;
      continue;
    }
    switch (arg) {
      case "-p":
      case "--print":
        options.print = true;
        break;
      case "-c":
      case "--continue":
        options.resume = { kind: "continue" };
        break;
      case "-r":
      case "--resume": {
        const next = args[index + 1];
        if (next !== undefined && !next.startsWith("-")) {
          options.resume = { kind: "id", value: next };
          index += 1;
        } else {
          options.resume = { kind: "pick" };
        }
        break;
      }
      case "--team":
        options.hostArgs.push("--team");
        break;
      case "--name":
        options.displayName = valueOf(args, index, arg);
        index += 1;
        break;
      case "--tunnel":
        options.tunnel = valueOf(args, index, arg);
        index += 1;
        break;
      case "--model":
        options.model = valueOf(args, index, arg);
        index += 1;
        break;
      case "--provider":
        options.provider = valueOf(args, index, arg);
        index += 1;
        break;
      case "--effort": {
        const value = valueOf(args, index, arg);
        if (!EFFORTS.includes(value)) {
          throw new UsageError(`--effort takes ${EFFORTS.join(", ")}`);
        }
        options.effort = value;
        index += 1;
        break;
      }
      case "--permission-mode":
        options.permissionMode = permissionModeOf(valueOf(args, index, arg));
        index += 1;
        break;
      case "--output-format": {
        const value = valueOf(args, index, arg) as OutputFormat;
        if (!FORMATS.includes(value)) {
          throw new UsageError(`--output-format takes ${FORMATS.join(", ")}`);
        }
        options.outputFormat = value;
        index += 1;
        break;
      }
      case "--allowedTools":
      case "--allowed-tools":
        options.allowedTools.push(...list(valueOf(args, index, arg)));
        index += 1;
        break;
      case "--disallowedTools":
      case "--disallowed-tools":
        options.disallowedTools.push(...list(valueOf(args, index, arg)));
        index += 1;
        break;
      default:
        if (arg.startsWith("-") && arg !== "-") {
          throw new UsageError(`unknown option ${arg}. plural --help lists the options`);
        }
        positional.push(arg);
    }
  }
  if (positional.length > 0) {
    options.prompt = positional.join(" ");
  }
  if (options.resume !== null && options.hostArgs.includes("--room")) {
    throw new UsageError("use either --resume or --room, not both");
  }
  if (options.print && options.prompt === null && process.stdin.isTTY === true) {
    throw new UsageError("-p needs a prompt: plural -p \"your question\", or pipe text into it");
  }
  return options;
}
