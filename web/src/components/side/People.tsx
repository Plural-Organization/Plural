import { useState } from "react";
import { label, type Command, type Participant, type Projection } from "@plural/client";
import { colorFor } from "../../lib/colors";
import { cx } from "../../lib/cx";
import { Section } from "./Section";
import styles from "./Sidebar.module.css";

interface PeopleProps {
  projection: Projection;
  isHost: boolean;
  send: (command: Command) => void;
  onInvite: (role: "participant" | "viewer") => void;
}

function order(a: Participant, b: Participant): number {
  return Number(b.role === "host") - Number(a.role === "host") || Number(b.connected) - Number(a.connected) || a.name.localeCompare(b.name);
}

export function People({ projection, isHost, send, onInvite }: PeopleProps) {
  const state = projection.state;
  const [menu, setMenu] = useState<string | null>(null);
  const act = (command: Command) => {
    send(command);
    setMenu(null);
  };

  return (
    <Section title="in the room">
      <ul className={styles.people}>
        {Object.values(state.participants)
          .sort(order)
          .map((person) => {
            const typing = projection.typing.has(person.id) && person.id !== projection.meId;
            return (
              <li key={person.id} className={cx(styles.person, !person.connected && styles.away)}>
                <span className={styles.dot} style={{ background: person.connected ? colorFor(person.id) : undefined }} />
                <span className={styles.name}>
                  {label(state, person)}
                  {person.id === projection.meId ? <span className="muted"> · you</span> : null}
                </span>
                <span className={styles.role}>{typing ? <span className={styles.typing}>typing…</span> : person.role}</span>
                {isHost && person.role !== "host" ? (
                  <button
                    type="button"
                    className="link-button"
                    aria-expanded={menu === person.id}
                    aria-label={`Manage ${person.name}`}
                    onClick={() => setMenu(menu === person.id ? null : person.id)}
                  >
                    ⋯
                  </button>
                ) : null}
                {menu === person.id ? (
                  <div className={styles.menu}>
                    <button
                      type="button"
                      onClick={() =>
                        act({ type: "participant.set_role", participant_id: person.id, role: person.role === "viewer" ? "participant" : "viewer" })
                      }
                    >
                      {person.role === "viewer" ? "let them prompt" : "make a viewer"}
                    </button>
                    <button type="button" className={styles.remove} onClick={() => act({ type: "participant.revoke", participant_id: person.id })}>
                      remove from the room
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
      </ul>
      {isHost ? (
        <div className={styles.actions}>
          <button className="button small" type="button" onClick={() => onInvite("participant")}>
            room link
          </button>
          <button className="button small ghost" type="button" onClick={() => onInvite("viewer")}>
            one-time viewer invite
          </button>
        </div>
      ) : null}
    </Section>
  );
}
