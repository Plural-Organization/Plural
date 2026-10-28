import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { mentionCompletions, mentionNote, type Mentionable, type ProposalView, type Role } from "@plural/client";
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
  onSubmit: (text: string) => void;
  onCancelEdit: () => void;
  onEscape: () => void;
  onActivity: (text: string) => void;
}

export function Composer({ role, people = [], placeholder, disabled, editing, quote = null, onSubmit, onCancelEdit, onEscape, onActivity }: ComposerProps) {
  const [value, setValue] = useState("");
  const [pick, setPick] = useState(0);
  const area = useRef<HTMLTextAreaElement>(null);
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

  return (
    <div className={styles.composer}>
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
      <div className={styles.row}>
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
