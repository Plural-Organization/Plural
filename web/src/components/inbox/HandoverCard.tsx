import type { Command, HandoverView, SessionState } from "@plural/client";
import { cx } from "../../lib/cx";
import { Action } from "./Action";
import styles from "./Inbox.module.css";

interface HandoverCardProps {
  offer: HandoverView;
  state: SessionState;
  send: (command: Command) => void;
}

// The host's seat is offered to this person. A browser cannot run the host (the agent runs on a computer), so taking it
// happens in the terminal client on the computer that should host; here the person can see the offer and decline it.
export function HandoverCard({ offer, state, send }: HandoverCardProps) {
  const host = Object.values(state.participants).find((person) => person.role === "host");
  return (
    <div className={cx(styles.card, styles.join)}>
      <div className={styles.head}>
        <span>
          <b>{host?.name ?? "The host"}</b> offers you the host of this room
        </span>
      </div>
      <p className={styles.why}>
        The conversation and the room link stay as they are; the agent would then work on your computer, with your model key. Taking it happens in the terminal: run{" "}
        <code>plural</code> there with this room open and press <b>y</b> on this offer.
      </p>
      <div className={styles.actions}>
        <Action hint="n" onPress={() => send({ type: "host.handover_answer", accept: false })}>decline</Action>
      </div>
    </div>
  );
}
