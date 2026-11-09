import { Button } from "@heroui/react";
import { ArrowUp, FileText, Paperclip, X } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { mentionCompletions, mentionNote, type Mentionable, type ProposalView, type Role } from "@plural/client";
import type { Attachment } from "../hooks/useAttachments";
import { suggestions, type CommandHint } from "../lib/commands";
import { withQuote } from "../lib/quote";
import styles from "./Composer.module.css";

const MAX_HEIGHT = 240;

interface ComposerProps {
  role: Role | undefined;
  people?: Mentionable[];
  commands?: CommandHint[];
  placeholder: string;
  disabled: string | null;
  editing: ProposalView | null;
  // A new key adds its text to the draft as a quote.
  quote?: { text: string; key: number } | null;
  // Files waiting to go with the next prompt; without onAttach the composer takes no files.
  attachments?: Attachment[];
  onAttach?: (files: File[]) => void;
  onDetach?: (key: string) => void;
  onSubmit: (text: string) => void;
  onCancelEdit: () => void;
  onEscape: () => void;
  onActivity: (text: string) => void;
}

export function Composer({ role, commands, people = [], placeholder, disabled, editing, quote = null, attachments = [], onAttach, onDetach, onSubmit, onCancelEdit, onEscape, onActivity }: ComposerProps) {
  const [value, setValue] = useState("");
  const [pick, setPick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const commandHints = suggestions(value, role, commands);
  const mentions = commandHints.length === 0 ? mentionCompletions(value, people) : [];
  const hints = [
    ...commandHints.map((hint) => ({ key: hint.name, usage: hint.usage, description: hint.description, insert: `/${hint.name}${hint.usage.includes(" ") ? " " : ""}` })),
    ...mentions.map(({ person, insert }) => ({ key: person.id, usage: `@${person.label}`, description: mentionNote(person), insert })),
  ];

  useEffect(() => {
    if (editing) {
      setValue(editing.text);
      area.current?.focus();
    }
  }, [editing?.id]);

  useEffect(() => {
    if (quote === null || disabled !== null) {
      return;
    }
    setValue((draft) => withQuote(draft, quote.text));
    // After the mouse is released, so the click that quoted does not take the focus back.
    const timer = setTimeout(() => {
      const element = area.current;
      if (element) {
        element.focus();
        element.setSelectionRange(element.value.length, element.value.length);
        element.scrollTop = element.scrollHeight;
      }
    }, 120);
    return () => clearTimeout(timer);
  }, [quote?.key]);

  useEffect(() => {
    const element = area.current;
    if (element) {
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
    }
  }, [value]);

  useEffect(() => setPick(0), [hints.length]);
  // The list scrolls, so the one picked with the arrows stays in view.
  const list = useRef<HTMLUListElement>(null);
  useEffect(() => {
    list.current?.children[pick]?.scrollIntoView({ block: "nearest" });
  }, [pick]);

  const submit = () => {
    const text = value.trim();
    if (text === "" && attachments.length === 0) {
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
        setValue(hint.insert);
      } else {
        setPick((current) => (current + (event.key === "ArrowDown" ? 1 : hints.length - 1)) % hints.length);
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      // With a suggestion open, Enter takes it, as Tab does; once nothing is left to complete, it sends.
      const hint = hints[pick] ?? hints[0];
      if (hint !== undefined && hint.insert.trimEnd() !== value.trimEnd()) {
        setValue(hint.insert);
        return;
      }
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

  const paste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = [...event.clipboardData.files];
    if (onAttach && files.length > 0) {
      event.preventDefault();
      onAttach(files);
    }
  };

  const drop = (event: DragEvent<HTMLDivElement>) => {
    setDragging(false);
    const files = [...event.dataTransfer.files];
    if (onAttach && files.length > 0) {
      event.preventDefault();
      onAttach(files);
    }
  };

  // A tip starts what its key would: a command on an empty line, a mention after the text.
  const begin = (key: "/" | "@") => {
    const next = key === "/" ? (value.trim() === "" ? "/" : value) : value === "" || /\s$/.test(value) ? `${value}@` : `${value} @`;
    setValue(next);
    onActivity(next);
    area.current?.focus();
  };

  return (
    <div
      className={styles.composer}
      onDragOver={(event) => {
        if (onAttach && event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
    >
      {hints.length > 0 ? (
        <ul ref={list} className={styles.hints} role="listbox" aria-label="Suggestions">
          {hints.map((hint, index) => (
            <li key={hint.key} role="option" aria-selected={index === pick}>
              <span className="mono">{hint.usage}</span>
              <span className="muted">{hint.description}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {editing ? <div className={styles.editing}>editing the proposal · enter sends it to the agent, esc cancels</div> : null}
      {attachments.length > 0 ? (
        <ul className={styles.files} aria-label="Files to send">
          {attachments.map((item) => (
            <li key={item.key} className={styles.file}>
              {item.preview ? <img src={item.preview} alt="" /> : <span className={styles.icon}><FileText size={18} /></span>}
              <span className={styles.fileName}>{item.name}</span>
              {item.sha256 === "" ? <span className="muted">loading…</span> : null}
              <span className="muted">{item.size < 1e6 ? `${Math.max(1, Math.round(item.size / 1e3))} KB` : `${(item.size / 1e6).toFixed(1)} MB`}</span>
              <Button isIconOnly size="sm" variant="ghost" aria-label={`Remove ${item.name}`} onPress={() => onDetach?.(item.key)}>
                <X size={14} />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className={`${styles.box} ${dragging ? styles.dragging : ""}`}>
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
          onPaste={paste}
          aria-label="Message the room"
        />
        <div className={styles.tools}>
          {onAttach ? (
            <>
              <Button isIconOnly size="sm" variant="ghost" aria-label="Attach files or images" isDisabled={disabled !== null} onPress={() => picker.current?.click()}>
                <Paperclip size={18} />
              </Button>
              <input
                ref={picker}
                type="file"
                multiple
                hidden
                onChange={(event) => {
                  onAttach([...(event.target.files ?? [])]);
                  event.target.value = "";
                }}
              />
            </>
          ) : null}
          <span className={styles.tips}>
            <button type="button" className={styles.tip} disabled={disabled !== null} onClick={() => begin("/")}>
              <kbd>/</kbd> commands
            </button>
            <button type="button" className={styles.tip} disabled={disabled !== null} onClick={() => begin("@")}>
              <kbd>@</kbd> people
            </button>
          </span>
          <Button isIconOnly size="sm" className="ml-auto" aria-label="send" isDisabled={disabled !== null || (value.trim() === "" && attachments.length === 0)} onPress={submit}>
            <ArrowUp size={16} weight="bold" />
          </Button>
        </div>
      </div>
    </div>
  );
}
