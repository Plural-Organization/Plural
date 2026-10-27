import { useState } from "react";
import { label, ruleLine, type Command, type Projection } from "@plural/client";
import { colorFor } from "./colors";

interface SidebarProps {
  projection: Projection;
  status: string;
  waiting: number;
  send: (command: Command) => void;
  onInvite: (role: "participant" | "viewer") => void;
}

export function Sidebar({ projection, status, waiting, send, onInvite }: SidebarProps) {
  const state = projection.state;
  const me = projection.me;
  const isHost = me?.role === "host";
  const [menu, setMenu] = useState<string | null>(null);
  const people = Object.values(state.participants).sort(
    (a, b) => Number(b.role === "host") - Number(a.role === "host") || Number(b.connected) - Number(a.connected) || a.name.localeCompare(b.name),
  );

  return (
    <aside className="side" aria-label="The room">
      <section>
        <h2>in the room</h2>
        <ul className="people">
          {people.map((person) => {
            const typing = projection.typing.has(person.id) && person.id !== projection.meId;
            return (
              <li key={person.id} className={person.connected ? "" : "away"}>
                <span className="dot" style={{ background: person.connected ? colorFor(person.id) : undefined }} />
                <span className="person">
                  {label(state, person)}
                  {person.id === projection.meId ? <span className="muted"> · you</span> : null}
                </span>
                <span className="role">{typing ? <span className="typing">typing…</span> : person.role}</span>
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
                  <div className="person-menu">
                    <button
                      type="button"
                      onClick={() => {
                        send({ type: "participant.set_role", participant_id: person.id, role: person.role === "viewer" ? "participant" : "viewer" });
                        setMenu(null);
                      }}
                    >
                      {person.role === "viewer" ? "let them prompt" : "make a viewer"}
                    </button>
                    <button
                      type="button"
                      className="danger"
                      onClick={() => {
                        send({ type: "participant.revoke", participant_id: person.id });
                        setMenu(null);
                      }}
                    >
                      remove from the room
                    </button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
        {isHost ? (
          <div className="side-actions">
            <button className="button small" type="button" onClick={() => onInvite("participant")}>
              invite
            </button>
            <button className="button small ghost" type="button" onClick={() => onInvite("viewer")}>
              invite a viewer
            </button>
          </div>
        ) : null}
      </section>

      {isHost ? (
        <section>
          <h2>waits for you</h2>
          <p className={waiting > 0 ? "attention" : "muted"}>{waiting > 0 ? `${waiting} above the input` : "nothing"}</p>
        </section>
      ) : null}

      <section>
        <h2>queue</h2>
        {state.queue.length === 0 ? (
          <p className="muted">empty</p>
        ) : (
          <ol className="queue">
            {state.queue.map((entry) => {
              const author = state.participants[entry.author_id];
              const mine = entry.author_id === projection.meId;
              return (
                <li key={entry.prompt_id}>
                  <span className="who" style={{ color: colorFor(entry.author_id) }}>
                    {author ? label(state, author) : entry.author_id}
                  </span>
                  <span className="text">{entry.text}</span>
                  {mine || isHost ? (
                    <button type="button" className="link-button" onClick={() => send({ type: "queue.cancel", prompt_id: entry.prompt_id })}>
                      cancel
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <section>
        <h2>agent</h2>
        <p className="mono">{state.agent || projection.agent || "starting…"}</p>
        <p className={state.run ? "running" : "muted"}>{state.run ? status || "working" : "idle"}</p>
        {isHost && state.run ? (
          <button className="button small danger" type="button" onClick={() => send({ type: "run.abort" })}>
            stop the run <kbd>esc</kbd>
          </button>
        ) : null}
      </section>

      <section>
        <h2>prompts</h2>
        {isHost ? (
          <div className="segmented" role="radiogroup" aria-label="Who may prompt">
            {(["open", "review"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={state.prompt_mode === mode}
                onClick={() => state.prompt_mode !== mode && send({ type: "session.set_prompt_mode", mode })}
              >
                {mode}
              </button>
            ))}
          </div>
        ) : null}
        <p className="muted">
          {state.prompt_mode === "open" ? "everyone talks to the agent directly" : "the host approves each prompt first"}
        </p>
      </section>

      {isHost ? (
        <section>
          <h2>session rules</h2>
          {state.policy.length === 0 ? (
            <p className="muted">none yet · {projection.basePolicy.length} built-in</p>
          ) : (
            <ul className="rules">
              {state.policy.map((rule) => (
                <li key={rule.id}>
                  <span className="mono">{ruleLine(rule)}</span>
                  <button type="button" className="link-button" onClick={() => send({ type: "policy.remove", rule_id: rule.id })}>
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </aside>
  );
}
