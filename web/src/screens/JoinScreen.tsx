import { useState, type FormEvent } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { Logo } from "../components/Logo";
import { blockedByMixedContent, hostOf, unwrapLink } from "../lib/links";
import { forgetRoom, linkOf, rememberName, savedName, savedRooms, type SavedRoom } from "../lib/saved";
import styles from "./JoinScreen.module.css";

interface JoinScreenProps {
  notice: string | null;
  onJoin: (link: JoinLink, name: string) => void;
}

function initialLink(): string {
  return new URLSearchParams(window.location.search).get("join") ?? "";
}

export function JoinScreen({ notice, onJoin }: JoinScreenProps) {
  const [raw, setRaw] = useState(initialLink);
  const [name, setName] = useState(savedName);
  const [error, setError] = useState<string | null>(null);
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  const insecure = blockedByMixedContent(unwrapLink(raw), window.location.protocol);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("Type the name the room will see.");
      return;
    }
    let link: JoinLink;
    try {
      link = parseLink(unwrapLink(raw));
    } catch (problem) {
      setError(problem instanceof Error ? `The link ${problem.message}.` : String(problem));
      return;
    }
    if (link.invite === null && link.token === null) {
      setError("The link has no invite. Copy the whole line the host shared, including ?invite=…");
      return;
    }
    rememberName(trimmed);
    window.history.replaceState(null, "", window.location.pathname);
    onJoin(link, trimmed);
  };

  return (
    <main className={styles.join}>
      <section>
        <Logo size={220} dance className={styles.logo} label="Plural logo. Hover a person to make them dance." />
        <h1>join the room.</h1>
        <p className={styles.intro}>
          Paste the invite the host shared. The host starts a room with <code>plural</code> in their project, and the first line in
          their session is the invite.
        </p>
      </section>

      <section className={styles.panel}>
        {notice ? <div className="banner danger">{notice}</div> : null}
        <form className={styles.form} onSubmit={submit}>
          <label className="label" htmlFor="join-link">
            invite link
          </label>
          <input
            id="join-link"
            value={raw}
            onChange={(event) => {
              setRaw(event.target.value);
              setError(null);
            }}
            placeholder="ws://host:7777/r_…?invite=…"
            spellCheck={false}
            autoComplete="off"
          />
          <label className="label" htmlFor="join-name">
            your name
          </label>
          <input
            id="join-name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setError(null);
            }}
            placeholder="alia"
            maxLength={40}
            autoComplete="nickname"
          />
          {insecure ? (
            <p className="hint warn">
              This page is served over https, so the browser blocks plain ws:// links. Ask the host to share the room through a relay
              with wss://, or open this client over http on the same network.
            </p>
          ) : null}
          {error ? <p className="hint danger">{error}</p> : null}
          <button className="button primary" type="submit">
            join
          </button>
        </form>

        {rooms.length > 0 ? (
          <div>
            <h2 className="label">rooms you were in</h2>
            <ul className={styles.recent}>
              {rooms.map((room) => (
                <li key={room.room}>
                  <button className={styles.saved} type="button" onClick={() => onJoin(linkOf(room), room.name)}>
                    <span className="mono">{room.room}</span>
                    <span className="muted">
                      as {room.name} · {hostOf(room.url)}
                    </span>
                  </button>
                  <button
                    className="link-button"
                    type="button"
                    aria-label={`Forget ${room.room}`}
                    onClick={() => {
                      forgetRoom(room.room);
                      setRooms(savedRooms());
                    }}
                  >
                    forget
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <p className="hint">
          No room yet? Install Plural and run <code>plural</code> in your project.{" "}
          <a href="https://agent-plural.vercel.app" target="_blank" rel="noopener noreferrer">
            What is Plural?
          </a>
        </p>
      </section>
    </main>
  );
}
