import { Input } from "@heroui/react";
import { useState } from "react";
import type { PluginAsked } from "@plural/client";
import { Action } from "./Action";
import styles from "./Inbox.module.css";

interface PluginAskCardProps {
  ask: PluginAsked;
  answer: (askId: string, value: string | null) => void;
}

export function PluginAskCard({ ask, answer }: PluginAskCardProps) {
  const [typed, setTyped] = useState(ask.default);
  const reply = (value: string | null) => answer(ask.ask_id, value);
  const options = ask.kind === "confirm" ? ["yes", "no"] : ask.options;
  return (
    <div className={styles.card}>
      <div className={styles.head}>
        <span>
          <b>/{ask.command}</b> asks you
        </span>
        <span className="muted">only you see this</span>
      </div>
      <div>{ask.title}</div>
      {ask.kind === "input" ? (
        <form
          className={styles.actions}
          onSubmit={(event) => {
            event.preventDefault();
            reply(typed);
          }}
        >
          <Input value={typed} onChange={(event) => setTyped(event.target.value)} aria-label={ask.title} autoFocus className="min-w-0 flex-1" />
          <Action tone="primary" type="submit">send</Action>
          <Action onPress={() => reply(null)}>close</Action>
        </form>
      ) : (
        <div className={styles.actions}>
          {options.map((option, index) => (
            <Action key={option} tone={index === 0 ? "primary" : undefined} onPress={() => reply(option)}>
              {option}
            </Action>
          ))}
          <Action onPress={() => reply(null)}>close</Action>
        </div>
      )}
    </div>
  );
}
