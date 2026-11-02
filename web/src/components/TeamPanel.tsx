import { useState } from "react";
import { copyText } from "../lib/clipboard";
import { cx } from "../lib/cx";
import { reachable, teamJoinCommand, teamJoinLink, type SessionCard } from "../lib/team";
import type { TeamState } from "../hooks/useTeam";
import styles from "./TeamPanel.module.css";

const STATUS = { running: ["●", "working"], waiting: ["◆", "waiting for its host"], idle: ["○", "idle"] } as const;

interface TeamPanelProps {
  state: TeamState;
  // The room open here now, marked in the list.
  current?: string | null;
  onOpen: (card: SessionCard, url: string) => void;
  onNotice: (text: string) => void;
}

// The team's live sessions, like SPACES in the terminal: a click opens one as a viewer.
export function TeamPanel({ state, current = null, onOpen, onNotice }: TeamPanelProps) {
  const { team, sessions, error } = state;
  const [invite, setInvite] = useState<{ command: string; link: string } | null>(null);
  const [inviting, setInviting] = useState(false);
  if (team === null) {
    return null;
  }
  const isOwner = team.profile.member.role === "owner";

  const makeInvite = () => {
    setInviting(true);
    state
      .invite()
      .then(({ code }) => {
        const next = { command: teamJoinCommand(team.profile, code), link: teamJoinLink(team.profile, code, window.location) };
        setInvite(next);
        void copyText(next.link).then((ok) => ok && onNotice("team invite link copied · one use, valid for an hour"));
      })
      .catch((problem: unknown) => onNotice(problem instanceof Error ? problem.message : String(problem)))
      .finally(() => setInviting(false));
  };

  const open = (card: SessionCard) => {
    const url = reachable(card, window.location.protocol);
    if (url === null) {
      onNotice(`${card.owner}'s session is reached only over plain ws://, which an https page cannot open`);
      return;
    }
    onOpen(card, url);
  };

  return (
    <div className={styles.team}>
      <p className={styles.head}>
        <span className={styles.name}>{team.profile.team_name}</span>
        <span className="muted">
          you are {team.profile.member.name}
          {isOwner ? " · owner" : ""}
        </span>
      </p>
      {sessions.length === 0 ? (
        <p className="muted">nobody shares a session right now</p>
      ) : (
        <ul className={styles.list}>
          {sessions.map((card) => {
            const [mark, said] = STATUS[card.status] ?? STATUS.idle;
            const here = card.room === current;
            return (
              <li key={card.room}>
                <button
                  className={cx(styles.card, here && styles.here)}
                  type="button"
                  disabled={here}
                  onClick={() => open(card)}
                  title={here ? "you are in this session" : `watch ${card.owner}'s session`}
                >
                  <span className={cx(styles.status, styles[card.status])} aria-label={said}>
                    {mark}
                  </span>
                  <span className={styles.who}>
                    <b>{card.owner}</b>
                    <span className="muted">
                      {card.repo}
                      {card.branch ? ` · ${card.branch}` : ""}
                    </span>
                    {card.title ? <span className={styles.title}>{card.title}</span> : null}
                  </span>
                  {card.viewers > 0 ? <span className={styles.viewers}>👁 {card.viewers}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {error ? <p className="hint warn">{error}</p> : null}
      {invite ? (
        <div className={styles.invite}>
          <span className="label">for a browser</span>
          <code>{invite.link}</code>
          <span className="label">for the terminal</span>
          <code>{invite.command}</code>
          <div className={styles.row}>
            <button className="button small" type="button" onClick={() => void copyText(invite.link).then((ok) => ok && onNotice("link copied"))}>
              copy link
            </button>
            <button className="button small ghost" type="button" onClick={() => void copyText(invite.command).then((ok) => ok && onNotice("command copied"))}>
              copy command
            </button>
            <button className="button small ghost" type="button" onClick={() => setInvite(null)}>
              done
            </button>
          </div>
        </div>
      ) : null}
      <div className={styles.row}>
        {isOwner ? (
          <button className="button small" type="button" disabled={inviting} onClick={makeInvite} title="One use, valid for an hour">
            {inviting ? "making an invite…" : "invite to the team"}
          </button>
        ) : null}
        <button
          className="link-button"
          type="button"
          onClick={() => {
            if (window.confirm(`Leave ${team.profile.team_name}? You need a new invite to come back.`)) {
              void state.leave();
            }
          }}
        >
          leave team
        </button>
      </div>
    </div>
  );
}
