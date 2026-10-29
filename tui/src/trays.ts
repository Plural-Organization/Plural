import { label, ruleLine, type Projection, type Role } from "@plural/client";
import { visibleCommands } from "./commands";
import type { Row } from "./components/Tray";
import { colorFor, theme } from "./theme";

const KEYS: [string, string][] = [
  ["enter", "send"],
  ["shift+enter", "new line (ctrl+j in any terminal)"],
  ["tab", "approvals and proposals, or complete a command"],
  ["shift+tab", "cycle permissions: ask · accept edits · plan · auto"],
  ["esc", "close this panel, or interrupt the run"],
  ["pgup / pgdn", "scroll the conversation"],
  ["ctrl+f", "search the conversation: text, commands, paths"],
  ["ctrl+o", "expand or collapse tool details"],
  ["ctrl+b", "show or hide the side panel"],
  ["ctrl+y", "copy the last reply"],
  ["ctrl+c", "clear the input, twice to quit"],
];

export function helpRows(role: Role | undefined): Row[] {
  const commands = visibleCommands(role);
  const name = Math.max(...commands.map((command) => command.name.length)) + 3;
  const key = Math.max(...KEYS.map(([shortcut]) => shortcut.length)) + 2;
  return [
    [{ text: "commands", fg: theme.dim }, { text: "  · tab completes, /<name> shows the arguments", fg: theme.dim }],
    ...commands.map((command): Row => [
      { text: `/${command.name}`.padEnd(name), fg: theme.accent },
      { text: command.description, fg: theme.text },
      { text: command.hostOnly ? "  host" : "", fg: theme.dim },
    ]),
    [""],
    [{ text: "keys", fg: theme.dim }],
    ...KEYS.map(([shortcut, action]): Row => [{ text: shortcut.padEnd(key), fg: theme.info }, { text: action, fg: theme.text }]),
  ];
}

export function whoRows(projection: Projection): Row[] {
  const state = projection.state;
  const people = Object.values(state.participants).sort((a, b) => Number(b.connected) - Number(a.connected));
  return people.map((person): Row => [
    { text: person.connected ? "● " : "○ ", fg: person.connected ? theme.ok : theme.dim },
    { text: label(state, person), fg: colorFor(person.id), bold: true },
    { text: person.id === projection.meId ? " (you)" : "", fg: theme.dim },
    { text: `  ${person.role}`, fg: person.role === "host" ? theme.accent : theme.dim },
    { text: person.connected ? "" : "  away", fg: theme.dim },
  ]);
}

export function skillRows(projection: Projection, width: number): Row[] {
  const skills = projection.state.skills;
  if (skills.length === 0) {
    return [[{ text: "no skills yet · ", fg: theme.dim }, { text: "/skills search <query>", fg: theme.accent }, { text: " finds some on skills.sh", fg: theme.dim }]];
  }
  const name = Math.max(...skills.map((skill) => skill.name.length));
  const room = Math.max(10, width - name - 14);
  return [
    ...skills.map((skill): Row => [
      { text: skill.name.padEnd(name + 2), fg: theme.text, bold: true },
      { text: skill.scope === "global" ? "global  " : "project ", fg: skill.scope === "global" ? theme.info : theme.ok },
      { text: skill.description.length > room ? `${skill.description.slice(0, room - 1)}…` : skill.description, fg: theme.dim },
    ]),
    [""],
    [{ text: "/skills search <query>", fg: theme.accent }, { text: " finds more · ", fg: theme.dim }, { text: "/skills rm <name>", fg: theme.accent }, { text: " removes one", fg: theme.dim }],
  ];
}

export function policyRows(projection: Projection): Row[] {
  const rules = projection.state.policy;
  const tint = { allow: theme.ok, ask: theme.warn, deny: theme.danger } as const;
  return [
    [{ text: `${projection.basePolicy.length} built-in rules, `, fg: theme.dim }, { text: `${rules.length} for this session`, fg: theme.dim }],
    ...rules.map((rule): Row => [{ text: rule.action.padEnd(6), fg: tint[rule.action], bold: true }, { text: ruleLine(rule).slice(6), fg: theme.text }, { text: `  ${rule.id}`, fg: theme.dim }]),
  ];
}

function tokens(count: number): string {
  return count >= 1_000_000 ? `${(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${Math.round(count / 1000)}K` : String(count);
}

export function usageRows(projection: Projection): Row[] {
  const lines = projection.state.usage;
  if (lines.length === 0) {
    return [[{ text: "nothing spent yet in this session", fg: theme.dim }]];
  }
  const label = (line: (typeof lines)[number]): string =>
    line.agent === "" ? "conversation" : line.agent === "compact" ? "summaries" : `agent ${line.agent}`;
  const width = Math.max(...lines.map((line) => `${line.role} · ${line.model}`.length));
  const what = Math.max(...lines.map((line) => label(line).length));
  const total = lines.reduce(
    (sum, line) => ({
      input: sum.input + line.usage.input_tokens + line.usage.cache_read_tokens + line.usage.cache_write_tokens,
      output: sum.output + line.usage.output_tokens,
    }),
    { input: 0, output: 0 },
  );
  return [
    ...lines.map((line): Row => [
      { text: `${line.role} · ${line.model}`.padEnd(width + 2), fg: line.role === "fast" ? theme.info : theme.accent },
      { text: label(line).padEnd(what + 2), fg: theme.text },
      { text: `${line.uses}×`.padStart(5), fg: theme.dim },
      { text: `  in ${tokens(line.usage.input_tokens)}`.padEnd(11), fg: theme.text },
      { text: `out ${tokens(line.usage.output_tokens)}`.padEnd(10), fg: theme.text },
      { text: line.usage.cache_read_tokens > 0 ? `cache ${tokens(line.usage.cache_read_tokens)}` : "", fg: theme.dim },
    ]),
    [""],
    [{ text: "total  ", fg: theme.dim }, { text: `in ${tokens(total.input)} · out ${tokens(total.output)} tokens`, fg: theme.text, bold: true }],
  ];
}
