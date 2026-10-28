import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from "react";
import { mentionCompletions, mentionNote, type Mentionable, type ProposalView, type Role } from "@plural/client";
import type { Attachment } from "../hooks/useAttachments";
import { suggestions } from "../lib/commands";
import { withQuote } from "../lib/quote";
import styles from "./Composer.module.css";

const MAX_HEIGHT = 240;

interface ComposerProps {
  role: Role | undefined;
  people?: Mentionable[];
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

export function Composer({ role, people = [], placeholder, disabled, editing, quote = null, attachments = [], onAttach, onDetach, onSubmit, onCancelEdit, onEscape, onActivity }: ComposerProps) {
  const [value, setValue] = useState("");
  const [pick, setPick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const commandHints = suggestions(value, role);
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
        <ul className={styles.hints} role="listbox" aria-label="Suggestions">
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
              {item.preview ? <img src={item.preview} alt="" /> : <span className={styles.icon}>📄</span>}
              <span className={styles.fileName}>{item.name}</span>
              <span className="muted">{item.size < 1e6 ? `${Math.max(1, Math.round(item.size / 1e3))} KB` : `${(item.size / 1e6).toFixed(1)} MB`}</span>
              <button type="button" className="link-button" aria-label={`Remove ${item.name}`} onClick={() => onDetach?.(item.key)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className={`${styles.row} ${dragging ? styles.dragging : ""}`}>
        {onAttach ? (
          <>
            <button
              type="button"
              className={styles.attach}
              aria-label="Attach files or images"
              title="Attach files or images"
              disabled={disabled !== null}
              onClick={() => picker.current?.click()}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21.4 11.1 12.2 20.3a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
              </svg>
            </button>
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
        <button className="button primary" type="button" onClick={submit} disabled={disabled !== null || (value.trim() === "" && attachments.length === 0)}>
          send
        </button>
      </div>
    </div>
  );
}
