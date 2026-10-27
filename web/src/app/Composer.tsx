import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { ProposalView, Role } from "@plural/client";

export interface CommandHint {
  name: string;
  usage: string;
  description: string;
  hostOnly?: boolean;
}

export const COMMANDS: CommandHint[] = [
  { name: "help", usage: "/help", description: "show commands and keys" },
  { name: "who", usage: "/who", description: "list participants" },
  { name: "invite", usage: "/invite [participant|viewer]", description: "create an invite link", hostOnly: true },
  { name: "mode", usage: "/mode open|review", description: "who may prompt directly", hostOnly: true },
  { name: "policy", usage: "/policy [allow|ask|deny <tool> <pattern> | rm <id>]", description: "show or edit permission rules", hostOnly: true },
  { name: "skills", usage: "/skills [search <q> | add <owner/repo@skill> [--global] | rm <name>]", description: "list, find and install skills" },
  { name: "compact", usage: "/compact", description: "summarize the context before the next prompt", hostOnly: true },
  { name: "abort", usage: "/abort", description: "stop the current run", hostOnly: true },
  { name: "cancel", usage: "/cancel <n>", description: "remove a queued prompt" },
  { name: "copy", usage: "/copy", description: "copy the last reply" },
  { name: "leave", usage: "/leave", description: "leave the room" },
];

export function helpText(role: Role | undefined): string {
  const commands = COMMANDS.filter((command) => !command.hostOnly || role === "host").map(
    (command) => `${command.usage.padEnd(34)} ${command.description}`,
  );
  const keys = [
    "enter                              send",
    "shift+enter                        new line",
    "y / a / n / b                      answer the approval card (host)",
    "esc                                stop the run (host, with an empty input)",
    "click a tool line                  open its output or diff",
  ];
  return ["commands", ...commands, "", "keys", ...keys].join("\n");
}

interface ComposerProps {
  role: Role | undefined;
  placeholder: string;
  disabled: string | null;
  editing: ProposalView | null;
  onSubmit: (text: string) => void;
  onCancelEdit: () => void;
  onEscape: () => void;
  onActivity: (text: string) => void;
}

export function Composer({ role, placeholder, disabled, editing, onSubmit, onCancelEdit, onEscape, onActivity }: ComposerProps) {
  const [value, setValue] = useState("");
  const [pick, setPick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const hints =
    value.startsWith("/") && !/\s/.test(value)
      ? COMMANDS.filter((command) => (!command.hostOnly || role === "host") && command.name.startsWith(value.slice(1).toLowerCase()))
      : [];

  useEffect(() => {
    if (editing) {
      setValue(editing.text);
      area.current?.focus();
    }
  }, [editing?.id]);

  useEffect(() => {
    const element = area.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 240)}px`;
    }
  }, [value]);

  useEffect(() => setPick(0), [hints.length]);

  const submit = () => {
    const text = value.trim();
    if (text === "") {
      return;
    }
    onSubmit(text);
    setValue("");
  };

  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (hints.length > 0 && (event.key === "Tab" || event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      if (event.key === "Tab") {
        const hint = hints[pick] ?? hints[0]!;
        setValue(`/${hint.name}${hint.usage.includes(" ") ? " " : ""}`);
      } else {
        setPick((current) => (current + (event.key === "ArrowDown" ? 1 : hints.length - 1)) % hints.length);
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    } else if (event.key === "Escape" && editing) {
      event.preventDefault();
      setValue("");
      onCancelEdit();
    } else if (event.key === "Escape" && hints.length > 0) {
      event.preventDefault();
      setValue("");
    } else if (event.key === "Escape" && value === "") {
      event.preventDefault();
      onEscape();
    }
  };

  return (
    <div className="composer">
      {hints.length > 0 ? (
        <ul className="hints" role="listbox" aria-label="Commands">
          {hints.map((hint, index) => (
            <li key={hint.name} role="option" aria-selected={index === pick}>
              <span className="mono">{hint.usage}</span>
              <span className="muted">{hint.description}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {editing ? <div className="editing">editing the proposal · enter sends it to the agent, esc cancels</div> : null}
      <div className="composer-row">
        <span className="caret" aria-hidden="true">
          ›
        </span>
        <textarea
          id="composer"
          ref={area}
          rows={1}
          value={value}
          disabled={disabled !== null}
          placeholder={disabled ?? placeholder}
          onChange={(event) => {
            setValue(event.target.value);
            onActivity(event.target.value);
          }}
          onKeyDown={keyDown}
          aria-label="Message the room"
        />
        <button className="button primary" type="button" onClick={submit} disabled={disabled !== null || value.trim() === ""}>
          send
        </button>
      </div>
    </div>
  );
}
