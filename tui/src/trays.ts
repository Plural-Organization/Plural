import {
  cacheHitLabel,
  cachedShare,
  callGraph,
  compactDuration,
  compactTokens,
  contextLines,
  label,
  missedCache,
  ruleLine,
  totalTokens,
  traceLines,
  traceTree,
  type Projection,
  type Role,
  type Span,
  type SpanStatus,
} from "@plural/client";
import { visibleCommands, type CommandHint } from "./commands";
import type { Row } from "./components/Tray";
import { colorFor, theme } from "./theme";

const KEYS: [string, string][] = [
  ["enter", "send"],
  ["shift+enter", "new line (ctrl+j in any terminal)"],
  ["tab", "approvals and proposals, or complete a command"],
  ["shift+tab", "cycle permissions: ask · accept edits · plan · auto"],
  ["esc", "close this panel, or interrupt the run"],
  ["pgup / pgdn", "scroll the conversation"],
  ["ctrl+f", "search: text, commands, paths, is:failed, is:prompt, by:name"],
  ["end", "jump to the latest message"],
  ["alt+↑ / alt+↓", "previous or next prompt"],
  ["ctrl+o", "expand or collapse tool details"],
  ["ctrl+b", "show or hide the side panel"],
  ["ctrl+y", "copy the last reply"],
  ["ctrl+c", "clear the input, twice to quit"],
];

export function helpRows(role: Role | undefined, plugins: CommandHint[] = []): Row[] {
  const commands = visibleCommands(role, plugins);
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
      skill.builtin
        ? { text: "built-in", fg: theme.dim }
        : { text: skill.scope === "global" ? "global  " : "project ", fg: skill.scope === "global" ? theme.info : theme.ok },
      { text: skill.description.length > room ? `${skill.description.slice(0, room - 1)}…` : skill.description, fg: theme.dim },
      ...(skill.hidden ? [{ text: `  /skill:${skill.name} only`, fg: theme.info }] : []),
    ]),
    [""],
    [{ text: "/skills search <query>", fg: theme.accent }, { text: " finds more · ", fg: theme.dim }, { text: "/skills rm <name>", fg: theme.accent }, { text: " removes one", fg: theme.dim }],
  ];
}

export function pluginRows(projection: Projection): Row[] {
  const plugins = projection.state.plugins;
  const host = projection.me?.role === "host";
  if (plugins.length === 0) {
    return [
      host
        ? [{ text: "no plugins yet · ", fg: theme.dim }, { text: "/plugins new <name>", fg: theme.accent }, { text: " creates one in ~/.plural/plugins", fg: theme.dim }]
        : [{ text: "no plugins yet · the host can add some", fg: theme.dim }],
    ];
  }
  const name = Math.max(...plugins.map((plugin) => plugin.name.length));
  return [
    ...plugins.map((plugin): Row => {
      const loaded = plugin.status === "loaded";
      const provided = [...plugin.commands.map((command) => `/${command}`), ...(plugin.tools ?? []).map((tool) => `${tool}()`)];
      const commands = provided.length > 0 ? provided.join(" ") : "no commands or tools";
      return [
        { text: loaded ? "✓ " : "✕ ", fg: loaded ? theme.ok : theme.danger },
        { text: plugin.name.padEnd(name + 2), fg: theme.text, bold: true },
        { text: loaded ? commands : (plugin.error ?? "failed to load"), fg: loaded ? theme.accent : theme.danger },
        { text: host ? `  ${plugin.path}` : "", fg: theme.dim },
      ];
    }),
    ...(host
      ? [
          [""] as Row,
          [
            { text: "/plugins new <name>", fg: theme.accent },
            { text: " creates one · ", fg: theme.dim },
            { text: "/plugins rm <name>", fg: theme.accent },
            { text: " deletes one · ", fg: theme.dim },
            { text: "/plugins reload", fg: theme.accent },
            { text: " applies your edits", fg: theme.dim },
          ] as Row,
        ]
      : []),
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
      input_tokens: sum.input_tokens + line.usage.input_tokens,
      cache_read_tokens: sum.cache_read_tokens + line.usage.cache_read_tokens,
      cache_write_tokens: sum.cache_write_tokens + line.usage.cache_write_tokens,
      output_tokens: sum.output_tokens + line.usage.output_tokens,
    }),
    { input_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, output_tokens: 0 },
  );
  const prompt = total.input_tokens + total.cache_read_tokens + total.cache_write_tokens;
  const cached = cacheHitLabel(total);
  return [
    ...lines.map((line): Row => [
      { text: `${line.role} · ${line.model}`.padEnd(width + 2), fg: line.role === "fast" ? theme.info : theme.accent },
      { text: label(line).padEnd(what + 2), fg: theme.text },
      { text: `${line.uses}×`.padStart(5), fg: theme.dim },
      { text: `  in ${tokens(line.usage.input_tokens)}`.padEnd(11), fg: theme.text },
      { text: `out ${tokens(line.usage.output_tokens)}`.padEnd(10), fg: theme.text },
      { text: line.usage.cache_read_tokens + line.usage.cache_write_tokens > 0 ? cacheHitLabel(line.usage) : "", fg: theme.dim },
    ]),
    [""],
    [
      { text: "total  ", fg: theme.dim },
      { text: `in ${tokens(prompt)} · out ${tokens(total.output_tokens)} tokens`, fg: theme.text, bold: true },
      { text: cached ? `  ${cached}` : "", fg: theme.dim },
      { text: total.cache_write_tokens > 0 ? ` · ${tokens(total.cache_write_tokens)} written to the cache` : "", fg: theme.dim },
    ],
    [{ text: "in counts the whole prompt, the part read from the cache too", fg: theme.dim }],
  ];
}

export function contextRows(projection: Projection): Row[] {
  const context = projection.state.context;
  if (context === null || context.parts.length === 0) {
    return [[{ text: "the agent has not been asked anything yet", fg: theme.dim }]];
  }
  const lines = contextLines(context);
  const width = Math.max(...lines.map((line) => line.label.length));
  const percent = (share: number): string => `${share > 0 && share < 0.01 ? "<1" : Math.round(share * 100)}%`;
  return [
    ...lines.map((line): Row => [
      { text: line.label.padEnd(width + 2), fg: theme.text },
      { text: tokens(line.tokens).padStart(6), fg: theme.text },
      { text: percent(line.share).padStart(6), fg: theme.dim },
    ]),
    [""],
    [
      { text: "total  ", fg: theme.dim },
      { text: `${tokens(context.tokens)} of ${tokens(context.window)}`, fg: theme.text, bold: true },
      { text: `  summarized at ${Math.round(context.compact_at * 100)}%`, fg: theme.dim },
    ],
    ...(context.hit === null
      ? []
      : [
          [
            { text: "latest request  ", fg: theme.dim },
            { text: `${Math.round(context.hit * 100)}% cached`, fg: missedCache(context) ? theme.warn : theme.text },
            { text: missedCache(context) ? "  most of it was sent at full price" : "", fg: theme.warn },
          ] as Row,
        ]),
    [{ text: "parts are estimated from their length and scaled to the provider's count", fg: theme.dim }],
  ];
}

const BAR = 8;
const BLOCKS = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉"];

/** A share of 0..1 as a bar of `BAR` cells, in eighths of a cell. */
function bar(share: number): string {
  const eighths = Math.round(Math.min(Math.max(share, 0), 1) * BAR * 8);
  return ("█".repeat(Math.floor(eighths / 8)) + (BLOCKS[eighths % 8] ?? "")).padEnd(BAR);
}

function statusColor(status: SpanStatus): string {
  return status === "error" || status === "denied" ? theme.danger : status === "running" ? theme.warn : status === "cancelled" ? theme.dim : theme.text;
}

const STATUS_MARK: Record<SpanStatus, string> = { ok: "", running: "…", error: "✕", denied: "⊘", cancelled: "■" };

function who(projection: Projection, actorId: string | null): string {
  return actorId === null ? "" : (projection.state.participants[actorId]?.name ?? "someone");
}

/** One run as a tree: each step, what it and everything under it spent, and how long it took. */
export function traceRows(projection: Projection, spans: readonly Span[], width: number): { title: string; rows: Row[] } {
  const roots = traceTree(spans);
  const root = roots[0];
  if (root === undefined) {
    return { title: "trace", rows: [[{ text: "no run has been traced yet: ask the agent something first", fg: theme.dim }]] };
  }
  const lines = traceLines(roots);
  // The tree and its details take what the numbers on the right leave.
  const left = Math.max(24, Math.min(width - (7 + BAR + 2 + 8 + 14), 72));
  const rows = lines.map((line): Row => {
    const span = line.node.span;
    const head = `${line.branch}${line.title}`;
    const detail = line.detail === "" ? "" : `  ${line.detail}`;
    const room = Math.max(0, left - head.length);
    const shown = detail.length > room ? `${detail.slice(0, Math.max(0, room - 1))}…` : detail;
    const cached = span.kind === "llm" ? cachedShare(line.node.totals) : null;
    const note = [
      STATUS_MARK[line.status],
      cached !== null && cached > 0 ? `${Math.round(cached * 100)}% cached` : "",
      span.kind === "approval" ? who(projection, span.actor_id) : "",
    ]
      .filter(Boolean)
      .join(" ");
    return [
      { text: line.branch, fg: theme.dim },
      { text: line.title, fg: span.kind === "llm" ? theme.accent : span.kind === "agent" ? theme.info : statusColor(line.status), bold: line.node.depth === 0 },
      { text: shown.padEnd(room), fg: theme.dim },
      { text: line.tokens.padStart(7), fg: theme.text },
      { text: ` ${bar(line.share)} `, fg: span.kind === "llm" ? theme.accent : theme.dim },
      { text: line.duration.padStart(7), fg: span.kind === "approval" ? theme.warn : theme.dim },
      { text: note === "" ? "" : `  ${note}`, fg: statusColor(line.status) === theme.text ? theme.dim : statusColor(line.status) },
    ];
  });
  const by = who(projection, root.span.actor_id);
  const totals = root.totals;
  const title = [
    "trace",
    by === "" ? "" : `run by ${by}`,
    `${compactTokens(totalTokens(totals))} tokens`,
    `${totals.models} model calls`,
    `${totals.tools} tool calls`,
    compactDuration(root.durationMs),
  ]
    .filter(Boolean)
    .join(" · ");
  return { title, rows };
}

/** Every run of the session added up: who called what, how often, and what it cost. */
export function callGraphRows(projection: Projection, spans: readonly Span[]): { title: string; rows: Row[] } {
  const graph = callGraph(spans, (id) => who(projection, id));
  if (graph.edges.length === 0) {
    return { title: "trace · session", rows: [[{ text: "no run has been traced yet", fg: theme.dim }]] };
  }
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const name = (id: string): string => nodes.get(id)?.label ?? id;
  const kind = (id: string): string => nodes.get(id)?.kind ?? "tool";
  const color = (id: string): string =>
    kind(id) === "person" ? theme.text : kind(id) === "agent" ? theme.info : kind(id) === "model" ? theme.accent : theme.dim;
  const from = Math.max(...graph.edges.map((edge) => name(edge.from).length));
  const to = Math.max(...graph.edges.map((edge) => name(edge.to).length));
  const most = Math.max(...graph.edges.map((edge) => edge.tokens), 1);
  const rows = graph.edges
    .slice()
    .sort((a, b) => b.tokens - a.tokens || b.calls - a.calls)
    .map((edge): Row => {
      const target = nodes.get(edge.to);
      return [
        { text: name(edge.from).padEnd(from), fg: color(edge.from) },
        { text: "  →  ", fg: theme.dim },
        { text: name(edge.to).padEnd(to + 2), fg: color(edge.to) },
        { text: `${edge.calls}×`.padStart(5), fg: theme.dim },
        { text: (edge.tokens > 0 ? compactTokens(edge.tokens) : "").padStart(8), fg: theme.text },
        { text: ` ${bar(edge.tokens / most)} `, fg: color(edge.to) },
        { text: target !== undefined && target.failed > 0 ? `${target.failed} failed` : "", fg: theme.danger },
      ];
    });
  const runs = traceTree(spans).length;
  return { title: `trace · session · ${runs} run${runs === 1 ? "" : "s"} · who called what`, rows };
}
