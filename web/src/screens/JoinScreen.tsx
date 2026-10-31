import { useState, type FormEvent } from "react";
import { parseLink, type JoinLink } from "@plural/client";
import { Logo } from "../components/Logo";
import { blockedByMixedContent, hostOf, unwrapLink } from "../lib/links";
import { forgetRoom, linkOf, rememberName, savedName, savedRooms, type SavedRoom } from "../lib/saved";
import { parseTeamInvite, type SessionCard } from "../lib/team";
import { TeamPanel } from "../components/TeamPanel";
import type { TeamState } from "../hooks/useTeam";
import styles from "./JoinScreen.module.css";

interface JoinScreenProps {
  notice: string | null;
  team: TeamState;
  onJoin: (link: JoinLink, name: string) => void;
  onWatch: (card: SessionCard, url: string) => void;
}

// A team member's name: what teammates see and @name uses.
const MEMBER_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/;

function initialLink(): string {
  return new URLSearchParams(window.location.search).get("join") ?? "";
}

// A team invite link carries ?team=<code>&relay=<url>.
function initialInvite(): string {
  return parseTeamInvite(window.location.href) === null ? "" : window.location.href;
}

export function JoinScreen({ notice, team, onJoin, onWatch }: JoinScreenProps) {
  const [raw, setRaw] = useState(initialLink);
  const [name, setName] = useState(savedName);
  const [error, setError] = useState<string | null>(null);
  const [rooms, setRooms] = useState<SavedRoom[]>(savedRooms);
  const insecure = blockedByMixedContent(unwrapLink(raw), window.location.protocol);
  const [teamInvite, setTeamInvite] = useState(initialInvite);
  const [teamError, setTeamError] = useState<string | null>(null);
  const [joiningTeam, setJoiningTeam] = useState(false);
  const [teamNote, setTeamNote] = useState<string | null>(null);
  const teamRelay = parseTeamInvite(teamInvite)?.relay ?? "";
  const teamInsecure = blockedByMixedContent(teamRelay, window.location.protocol);

  const joinTeam = (event: FormEvent) => {
    event.preventDefault();
    const invite = parseTeamInvite(teamInvite);
    if (invite === null) {
      setTeamError("Paste the command the owner shared, plural team join <code> --relay <url>, or their invite link.");
      return;
    }
    const member = name.trim();
    if (!MEMBER_NAME.test(member)) {
      setTeamError("Your name in the team: 1 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.");
      return;
    }
    setJoiningTeam(true);
    setTeamError(null);
    team
      .join(invite, member)
      .then(() => {
        rememberName(member);
        setTeamInvite("");
        window.history.replaceState(null, "", window.location.pathname);
      })
      .catch((problem: unknown) => setTeamError(problem instanceof Error ? problem.message : String(problem)))
      .finally(() => setJoiningTeam(false));
  };

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
    if (link.invite === null && link.token === null && link.join === null) {
      setError("The link has no invite or room code. Copy the whole line the host shared, including ?join=… or ?invite=…");
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
          Paste the link the host shared. The host starts a room with <code>plural</code> in their project, and the first line in
          their session is the room link. The host lets you in when you join.
        </p>
      </section>

      <section className={styles.panel}>
        {notice ? <div className="banner danger">{notice}</div> : null}
        <form className={styles.form} onSubmit={submit}>
          <label className="label" htmlFor="join-link">
            room link
          </label>
          <input
            id="join-link"
            value={raw}
            onChange={(event) => {
              setRaw(event.target.value);
              setError(null);
            }}
            placeholder="wss://host/r_…?join=…"
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

        {team.team !== null ? (
          <div>
            <h2 className="label">your team</h2>
            <TeamPanel state={team} onOpen={onWatch} onNotice={setTeamNote} />
            {teamNote ? <p className="hint">{teamNote}</p> : null}
          </div>
        ) : team.loading ? null : (
          <form className={styles.form} onSubmit={joinTeam}>
            <label className="label" htmlFor="team-invite">
              or join a team
            </label>
            <input
              id="team-invite"
              value={teamInvite}
              onChange={(event) => {
                setTeamInvite(event.target.value);
                setTeamError(null);
              }}
              placeholder="plural team join tm-… --relay wss://…"
              spellCheck={false}
              autoComplete="off"
            />
            <p className="hint">
              In a team you see everyone's shared sessions and open them without a room link. Your name above is your name in the team; it
              must differ from the one you use in the terminal.
            </p>
            {teamInsecure ? (
              <p className="hint warn">This page is served over https, so the browser cannot reach a team relay at ws://. The team needs a relay with wss://.</p>
            ) : null}
            {(teamError ?? team.error) ? <p className="hint danger">{teamError ?? team.error}</p> : null}
            <button className="button" type="submit" disabled={joiningTeam}>
              {joiningTeam ? "joining…" : "join the team"}
            </button>
          </form>
        )}

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
