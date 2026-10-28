import { contextMeter, type ConnectionStatus, type Projection } from "@plural/client";
import { cx } from "../lib/cx";
import { Logo } from "./Logo";
import styles from "./TopBar.module.css";

interface TopBarProps {
  room: string;
  projection: Projection;
  connection: ConnectionStatus;
  panelOpen: boolean;
  onCopyRoom: () => void;
  onTogglePanel: () => void;
  onLeave: () => void;
}

function connectionText(connection: ConnectionStatus, online: number): string {
  if (connection === "online") return `${online} in the room`;
  return connection === "connecting" ? "connecting…" : "reconnecting…";
}

export function TopBar({ room, projection, connection, panelOpen, onCopyRoom, onTogglePanel, onLeave }: TopBarProps) {
  const state = projection.state;
  const meter = contextMeter(state);
  const online = Object.values(state.participants).filter((person) => person.connected).length;
  return (
    <header className={styles.bar}>
      <div className={styles.brand}>
        <Logo size={22} />
        <span>plural</span>
      </div>
      <button className={cx("mono", styles.room)} type="button" title="Copy the room id" onClick={onCopyRoom}>
        {room}
      </button>
      <span className={cx(styles.pill, state.prompt_mode === "review" && styles.review)}>{state.prompt_mode} mode</span>
      <span className="grow" />
      {meter ? (
        <span className={cx(styles.meter, styles[meter.level])} title={`${meter.tokens} of ${meter.window} tokens in the context`}>
          <span className={styles.meterTrack}>
            <span className={styles.meterFill} style={{ width: `${meter.percent}%` }} />
          </span>
          context {meter.percent}%
        </span>
      ) : null}
      <span className={cx("mono", styles.agent)}>{projection.agentLabel}</span>
      <span className={cx(styles.connection, styles[connection])} title={connection}>
        <span className={styles.dot} />
        {connectionText(connection, online)}
      </span>
      <button className={cx("button small ghost", styles.panelToggle)} type="button" onClick={onTogglePanel} aria-expanded={panelOpen}>
        room
      </button>
      <button className="button small ghost" type="button" onClick={onLeave}>
        leave
      </button>
    </header>
  );
}
