import { useMemo, useState, type FormEvent } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { Logo } from "./Logo";
import { forgetRoom, linkOf, rememberName, savedName, savedRooms, type SavedRoom } from "./saved";

interface JoinScreenProps {
  notice: string | null;
  onJoin: (link: JoinLink, name: string) => void;
}

function hostOf(url: string): string {
  try {
    return new URL(url.replace(/^ws/, "http")).host;
  } catch {
    return url;
  }
}

function unwrap(raw: string): string {
  const text = raw.trim().replace(/^plural join\s+/, "").replace(/^["']|["']$/g, "");
  if (/^https?:\/\//.test(text)) {
    try {
      return new URL(text).searchParams.get("join") ?? text;
    } catch {
      return text;
    }
  }
  return text;
}

function initialLink(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("join") ?? "";
}

export function JoinScreen({ notice, onJoin }: JoinScreenProps) {
  const [raw, setRaw] = useState(initialLink);
  const [name, setName] = useState(savedName);
  const [error, setError] = useState<string | null>(null);
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  const insecure = useMemo(() => window.location.protocol === "https:" && unwrap(raw).startsWith("ws://"), [raw]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      setError("Type the name the room will see.");
      return;
    }
    let link: JoinLink;
    try {
      link = parseLink(unwrap(raw));
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
    <main className="join">
      <section className="join-intro">
        <Logo size={220} dance className="join-logo" label="Plural logo. Hover a person to make them dance." />
        <h1>join the room.</h1>
        <p>
          Paste the invite the host shared. The host starts a room with <code>plural</code> in their project, and the first line in
          their session is the invite.
        </p>
      </section>

      <section className="join-panel">
        {notice ? <div className="banner danger">{notice}</div> : null}
        <form className="join-form" onSubmit={submit}>
          <label htmlFor="join-link">invite link</label>
          <input
            id="join-link"
            value={raw}
            onChange={(event) => {
              setRaw(event.target.value);
              setError(null);
            }}
            placeholder='ws://host:7777/r_…?invite=…'
            spellCheck={false}
            autoComplete="off"
          />
          <label htmlFor="join-name">your name</label>
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
          <div className="recent">
            <h2>rooms you were in</h2>
            <ul>
              {rooms.map((room) => (
                <li key={room.room}>
                  <button className="recent-room" type="button" onClick={() => onJoin(linkOf(room), room.name)}>
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
          <a href="https://github.com/Plural-Organization/Plural" target="_blank" rel="noopener noreferrer">
            What is Plural?
          </a>
        </p>
      </section>
    </main>
  );
}
