import { label, type Command, type Projection } from "@plural/client";
import { colorFor } from "../../lib/colors";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

export function Queue({ projection, isHost, send }: { projection: Projection; isHost: boolean; send: (command: Command) => void }) {
  const state = projection.state;
  return (
    <Section title="queue">
      {state.queue.length === 0 ? (
        <p className="muted">empty</p>
      ) : (
        <ol className={styles.queue}>
          {state.queue.map((entry) => {
            const author = state.participants[entry.author_id];
            return (
              <li key={entry.prompt_id}>
                <span className={styles.author} style={{ color: colorFor(entry.author_id) }}>
                  {author ? label(state, author) : entry.author_id}
                </span>
                <span className={styles.text}>{entry.text}</span>
                {entry.author_id === projection.meId || isHost ? (
                  <button type="button" className="link-button" onClick={() => send({ type: "queue.cancel", prompt_id: entry.prompt_id })}>
                    cancel
                  </button>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}
