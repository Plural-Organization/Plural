import { useState } from "react";
import type { PluginAsked } from "@plural/client";
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
          <input value={typed} onChange={(event) => setTyped(event.target.value)} aria-label={ask.title} autoFocus />
          <button className="button primary" type="submit">
            send
          </button>
          <button className="button" type="button" onClick={() => reply(null)}>
            close
          </button>
        </form>
      ) : (
        <div className={styles.actions}>
          {options.map((option, index) => (
            <button key={option} className={index === 0 ? "button primary" : "button"} type="button" onClick={() => reply(option)}>
              {option}
            </button>
          ))}
          <button className="button" type="button" onClick={() => reply(null)}>
            close
          </button>
        </div>
      )}
    </div>
  );
}
