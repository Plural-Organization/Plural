import type { Command, PromptMode as Mode } from "@plural/client";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

const MODES: Mode[] = ["open", "review"];

export function PromptMode({ mode, isHost, send }: { mode: Mode; isHost: boolean; send: (command: Command) => void }) {
  return (
    <Section title="prompts">
      {isHost ? (
        <div className={styles.segmented} role="radiogroup" aria-label="Who may prompt">
          {MODES.map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={mode === option}
              onClick={() => mode !== option && send({ type: "session.set_prompt_mode", mode: option })}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
      <p className="muted">{mode === "open" ? "everyone talks to the agent directly" : "the host approves each prompt first"}</p>
    </Section>
  );
}
