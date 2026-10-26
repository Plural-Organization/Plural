import { useState } from "react";
import type { Role } from "@plural/client";
import { THEMES, THEME_NAMES, theme, type ThemeName } from "../theme";
import type { Settings } from "../settings";

export type RowId = "theme" | "prompts" | "panel" | "copy" | "bell" | "typing" | "invite" | "reply";

export interface Row {
  id: RowId;
  label: string;
  value: string;
  hint: string;
  enabled: boolean;
  kind: "choice" | "toggle" | "action";
}

export function settingsRows(settings: Settings, mode: "open" | "review", role: Role | undefined): Row[] {
  const host = role === "host";
  const on = (value: boolean) => (value ? "on" : "off");
  return [
    { id: "theme", label: "Theme", value: THEMES[settings.theme].label, hint: "colours of the whole interface", enabled: true, kind: "choice" },
    {
      id: "prompts",
      label: "Prompts",
      value: mode === "open" ? "open" : "host approves",
      hint: host ? "open: everyone prompts directly · review: you approve each prompt" : "only the host can change this",
      enabled: host,
      kind: "choice",
    },
    { id: "panel", label: "Side panel", value: on(settings.panel), hint: "participants, queue and approvals (ctrl+b)", enabled: true, kind: "toggle" },
    { id: "copy", label: "Copy on select", value: on(settings.copyOnSelect), hint: "selecting text puts it on the clipboard", enabled: true, kind: "toggle" },
    { id: "bell", label: "Bell on requests", value: on(settings.bell), hint: "ring the terminal when something needs the host", enabled: host, kind: "toggle" },
    { id: "typing", label: "Show my typing", value: on(settings.announceTyping), hint: "let others see when you are writing", enabled: role !== "viewer", kind: "toggle" },
    { id: "invite", label: "Invite link", value: "create and copy", hint: "a one-time link for a participant", enabled: host, kind: "action" },
    { id: "reply", label: "Last reply", value: "copy", hint: "put the agent's last answer on the clipboard", enabled: true, kind: "action" },
  ];
}

export function cycleTheme(current: ThemeName, direction: 1 | -1): ThemeName {
  const index = THEME_NAMES.indexOf(current);
  return THEME_NAMES[(index + direction + THEME_NAMES.length) % THEME_NAMES.length] as ThemeName;
}

export const DIALOG_WIDTH = 58;

interface DialogProps {
  rows: Row[];
  selected: number;
  width: number;
  height: number;
  agent: string;
  room: string;
  onSelect: (index: number) => void;
  onChange: (index: number, direction: 1 | -1) => void;
  onClose: () => void;
}

export function SettingsDialog({ rows, selected, width, height, agent, room, onSelect, onChange, onClose }: DialogProps) {
  const [closeHover, setCloseHover] = useState(false);
  const boxWidth = Math.min(DIALOG_WIDTH, Math.max(30, width - 4));
  const boxHeight = rows.length + 10;
  return (
    <box
      position="absolute"
      top={0}
      left={0}
      width={width}
      height={height}
      zIndex={20}
      onMouseDown={onClose}
      alignItems="center"
      justifyContent="center"
    >
      <box
        width={boxWidth}
        height={boxHeight}
        flexDirection="column"
        border
        borderStyle="rounded"
        borderColor={theme.accent}
        backgroundColor={theme.panel}
        paddingX={2}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <box flexDirection="row" justifyContent="space-between">
          <text>
            <span fg={theme.accent}>
              <b>⚙ settings</b>
            </span>
          </text>
          <box onMouseDown={onClose} onMouseOver={() => setCloseHover(true)} onMouseOut={() => setCloseHover(false)}>
            <text fg={closeHover ? theme.danger : theme.dim}>✕ esc</text>
          </box>
        </box>
        <text fg={theme.dim}>{" "}</text>
        {rows.map((row, index) => {
          const active = index === selected;
          const color = !row.enabled ? theme.dim : active ? theme.accent : theme.text;
          return (
            <box
              key={row.id}
              flexDirection="row"
              justifyContent="space-between"
              onMouseDown={(event) => {
                event.stopPropagation();
                onSelect(index);
                if (row.enabled) {
                  onChange(index, 1);
                }
              }}
            >
              <text fg={color}>
                {active ? "› " : "  "}
                {row.label}
              </text>
              <text fg={row.enabled ? (active ? theme.accent : theme.text) : theme.dim}>
                {row.kind === "choice" && row.enabled ? "‹ " : ""}
                {row.value}
                {row.kind === "choice" && row.enabled ? " ›" : ""}
              </text>
            </box>
          );
        })}
        <text fg={theme.dim}>{" "}</text>
        <text fg={theme.dim}>{rows[selected]?.hint ?? ""}</text>
        <text fg={theme.dim}>agent {agent || "unknown"}</text>
        <text fg={theme.dim}>room {room.slice(0, 26)}…</text>
        <text fg={theme.dim}>↑↓ select · ←→ change · enter apply · esc close</text>
      </box>
    </box>
  );
}
