import type { McpServerView, SkillHit } from "@plural/client";
import { MCP_CATALOG, type McpField } from "../mcpCatalog";
import { theme } from "../theme";
import { Spinner, useElapsed } from "./Spinner";

// A piece of a tray row: plain text or text with its own color and weight.
export type Bit = string | { text: string; fg?: string; bold?: boolean };
export type Row = Bit[];
export type Tone = "accent" | "warn" | "danger";

// The tray holds the output of the user's own commands, under the composer and out of the conversation.
export type Tray =
  | { kind: "text"; title: string; tone: Tone; rows: Row[] }
  | { kind: "busy"; title: string; text: string; key: number }
  | { kind: "pick"; title: string; hits: SkillHit[]; selected: number; canInstall: boolean }
  | { kind: "mcp"; selected: number; canManage: boolean }
  | McpWizard;

export type McpWizard = {
  kind: "mcp-add";
  step: "pick" | "field" | "scope";
  selected: number;
  preset: number;
  fields: McpField[];
  index: number;
  values: Record<string, string>;
  warning: string | null;
};

export const SCOPES = [
  { scope: "project", title: "This project", where: ".mcp.json in the workspace · commit it to share with the team" },
  { scope: "global", title: "Every project", where: "~/.plural/mcp.json on this machine" },
] as const;


function Line({ row }: { row: Row }) {
  return (
    <text wrapMode="none">
      {row.map((bit, index) =>
        typeof bit === "string" ? (
          <span key={index}>{bit}</span>
        ) : (
          <span key={index} fg={bit.fg}>
            {bit.bold ? <b>{bit.text}</b> : bit.text}
          </span>
        ),
      )}
    </text>
  );
}

function Busy({ text }: { text: string }) {
  const elapsed = useElapsed(true);
  return (
    <text>
      <Spinner color={theme.info} />
      <span fg={theme.info}> {text}…</span>
      <span fg={theme.dim}>{elapsed > 0 ? ` ${elapsed}s` : ""}</span>
    </text>
  );
}

export function installs(count: number): string {
  return count >= 1_000_000 ? `${(count / 1_000_000).toFixed(1)}M` : count >= 1000 ? `${Math.round(count / 1000)}K` : String(count);
}

function Pick({ tray, onSelect }: { tray: Extract<Tray, { kind: "pick" }>; onSelect: (index: number) => void }) {
  if (tray.hits.length === 0) {
    return <text fg={theme.dim}>nothing on skills.sh for that, try other words</text>;
  }
  const width = Math.max(...tray.hits.map((hit) => hit.package.length));
  const top = Math.max(...tray.hits.map((hit) => hit.installs), 1);
  return (
    <box flexDirection="column">
      {tray.hits.map((hit, index) => {
        const on = index === tray.selected;
        const bar = "▮".repeat(Math.max(1, Math.round((hit.installs / top) * 8)));
        return (
          <box key={hit.package} onMouseDown={() => onSelect(index)} backgroundColor={on ? theme.line : undefined}>
            <text wrapMode="none">
              <span fg={on ? theme.accent : theme.dim}>{on ? "› " : "  "}</span>
              <span fg={on ? theme.text : theme.dim}>{hit.package.padEnd(width)}</span>
              <span fg={theme.dim}>{"  "}</span>
              <span fg={on ? theme.ok : theme.line}>{bar.padEnd(8)}</span>
              <span fg={theme.dim}> {installs(hit.installs)}</span>
            </text>
          </box>
        );
      })}
    </box>
  );
}

function Action({ on, label, detail, onSelect }: { on: boolean; label: string; detail: string; onSelect: () => void }) {
  return (
    <box onMouseDown={onSelect} backgroundColor={on ? theme.line : undefined}>
      <text wrapMode="none">
        <span fg={on ? theme.accent : theme.dim}>{on ? "› " : "  "}</span>
        <span fg={on ? theme.accent : theme.info}>{label}</span>
        <span fg={theme.dim}>{`  ${detail}`}</span>
      </text>
    </box>
  );
}

function Servers({ servers, selected, canManage, onSelect }: { servers: readonly McpServerView[]; selected: number; canManage: boolean; onSelect: (index: number) => void }) {
  const actions = canManage ? (
    <>
      {servers.length > 0 ? <text> </text> : null}
      <Action on={selected === servers.length} label="+ add a server…" detail="pick from popular ones or bring your own" onSelect={() => onSelect(servers.length)} />
      <Action on={selected === servers.length + 1} label="⇣ import" detail="the servers set up for Claude Code and Cursor" onSelect={() => onSelect(servers.length + 1)} />
    </>
  ) : null;
  if (servers.length === 0) {
    return (
      <box flexDirection="column">
        <text fg={theme.dim}>no MCP servers yet</text>
        {actions}
      </box>
    );
  }
  const width = Math.max(...servers.map((server) => server.name.length));
  return (
    <box flexDirection="column">
      {servers.map((server, index) => {
        const on = index === selected;
        const mark =
          server.status === "ready" ? (
            <span fg={theme.ok}>●</span>
          ) : server.status === "connecting" ? (
            <Spinner color={theme.info} />
          ) : server.status === "failed" ? (
            <span fg={theme.danger}>✕</span>
          ) : (
            <span fg={theme.dim}>○</span>
          );
        const detail =
          server.status === "ready"
            ? `${server.tools} tools`
            : server.status === "connecting"
              ? "connecting…"
              : server.status === "failed"
                ? `failed: ${server.error ?? "unknown error"}`
                : "off";
        return (
          <box key={server.name} onMouseDown={() => onSelect(index)} backgroundColor={on ? theme.line : undefined}>
            <text wrapMode="none">
              <span fg={on ? theme.accent : theme.dim}>{on ? "› " : "  "}</span>
              {mark}
              <span fg={on ? theme.text : theme.dim}> {server.name.padEnd(width)}</span>
              <span fg={server.status === "failed" ? theme.danger : theme.dim}>{`  ${detail}`.padEnd(14)}</span>
              <span fg={theme.dim}>
                {"  "}
                {server.transport} · {server.scope}
              </span>
            </text>
          </box>
        );
      })}
      {actions}
    </box>
  );
}

function Wizard({ wizard, onSelect }: { wizard: McpWizard; onSelect: (index: number) => void }) {
  if (wizard.step === "pick") {
    const width = Math.max(...MCP_CATALOG.map((preset) => preset.title.length));
    return (
      <box flexDirection="column">
        {MCP_CATALOG.map((preset, index) => {
          const on = index === wizard.selected;
          const needs = preset.fields.filter((field) => field.secret && !field.optional).length > 0 ? "  · needs a token" : "";
          return (
            <box key={`${preset.title}`} onMouseDown={() => onSelect(index)} backgroundColor={on ? theme.line : undefined}>
              <text wrapMode="none">
                <span fg={on ? theme.accent : theme.dim}>{on ? "› " : "  "}</span>
                <span fg={on ? theme.text : theme.dim}>{preset.title.padEnd(width)}</span>
                <span fg={theme.dim}>{`  ${preset.blurb}`}</span>
                <span fg={theme.warn}>{needs}</span>
              </text>
            </box>
          );
        })}
      </box>
    );
  }
  const preset = MCP_CATALOG[wizard.preset]!;
  const answered = wizard.fields.slice(0, wizard.step === "scope" ? wizard.fields.length : wizard.index);
  return (
    <box flexDirection="column">
      {answered.map((field) => (
        <text key={field.key} wrapMode="none">
          <span fg={theme.ok}>✓ </span>
          <span fg={theme.dim}>{field.label}: </span>
          <span fg={theme.text}>{field.secret ? (wizard.values[field.key] ? "••••••••" : "skipped") : wizard.values[field.key] || "skipped"}</span>
        </text>
      ))}
      {wizard.step === "field" ? (
        <>
          <text>
            <span fg={theme.accent}>› </span>
            <b>{wizard.fields[wizard.index]!.label}</b>
            <span fg={theme.dim}>{`  step ${wizard.index + 1} of ${wizard.fields.length + 1}`}</span>
          </text>
          <text fg={theme.dim}>  {wizard.fields[wizard.index]!.hint ?? ""}{wizard.fields[wizard.index]!.hint ? " · " : ""}type it in the box above and press enter</text>
        </>
      ) : (
        SCOPES.map((option, index) => {
          const on = index === wizard.selected;
          return (
            <box key={option.scope} onMouseDown={() => onSelect(index)} backgroundColor={on ? theme.line : undefined}>
              <text wrapMode="none">
                <span fg={on ? theme.accent : theme.dim}>{on ? "› " : "  "}</span>
                <span fg={on ? theme.text : theme.dim}>{`Save for ${option.title.toLowerCase()}`}</span>
                <span fg={theme.dim}>{`  ${option.where}`}</span>
              </text>
            </box>
          );
        })
      )}
      {wizard.warning ? <text fg={theme.warn}>  {wizard.warning}</text> : null}
      <text fg={theme.dim}>{preset.title === "Your own command" || preset.title === "Your own URL" ? "" : `  ${preset.command?.join(" ") ?? preset.url ?? ""}`}</text>
    </box>
  );
}

const TONE = { accent: () => theme.accent, warn: () => theme.warn, danger: () => theme.danger } as const;

interface TrayProps {
  tray: Tray;
  servers: readonly McpServerView[];
  maxRows: number;
  onClose: () => void;
  onSelect: (index: number) => void;
}

export function TrayView({ tray, servers, maxRows, onClose, onSelect }: TrayProps) {
  const color = tray.kind === "text" ? TONE[tray.tone]() : tray.kind === "busy" ? theme.info : theme.accent;
  const title =
    tray.kind === "mcp-add"
      ? tray.step === "pick"
        ? "add an MCP server"
        : `add ${MCP_CATALOG[tray.preset]!.title}`
      : tray.kind === "mcp"
      ? `mcp · ${servers.filter((server) => server.status === "ready").length}/${servers.length} connected · ${servers.reduce((sum, server) => sum + server.tools, 0)} tools`
      : tray.title;
  const footer =
    tray.kind === "mcp-add"
      ? tray.step === "field"
        ? "enter next · empty enter takes the default or skips · esc cancel"
        : "↑↓ choose · enter select · esc cancel"
      : tray.kind === "mcp"
      ? tray.canManage
        ? "↑↓ choose · enter on/off or run · ctrl+r restart · esc close"
        : "esc close"
      : tray.kind === "pick"
      ? tray.hits.length > 0 && tray.canInstall
        ? "↑↓ choose · enter install here · ctrl+g for every project · esc close"
        : "esc close"
      : tray.kind === "busy"
        ? "esc hide"
        : "esc close";
  const rows = tray.kind === "text" ? tray.rows : [];
  const shown = rows.slice(0, maxRows);
  return (
    <box
      flexDirection="column"
      flexShrink={0}
      marginX={2}
      border
      borderStyle="rounded"
      borderColor={color}
      title={` ${title} `}
      titleAlignment="left"
      paddingX={1}
    >
      {tray.kind === "text" ? (
        <>
          {shown.map((row, index) => (
            <Line key={index} row={row} />
          ))}
          {rows.length > maxRows ? <text fg={theme.dim}>… {rows.length - maxRows} more, make the terminal taller to see them</text> : null}
        </>
      ) : tray.kind === "busy" ? (
        <Busy key={tray.key} text={tray.text} />
      ) : tray.kind === "mcp-add" ? (
        <Wizard wizard={tray} onSelect={onSelect} />
      ) : tray.kind === "mcp" ? (
        <Servers servers={servers} selected={tray.selected} canManage={tray.canManage} onSelect={onSelect} />
      ) : (
        <Pick tray={tray} onSelect={onSelect} />
      )}
      <box flexDirection="row" justifyContent="space-between">
        <text fg={theme.dim}>{footer}</text>
        <box onMouseDown={onClose}>
          <text fg={theme.dim}>✕</text>
        </box>
      </box>
    </box>
  );
}
