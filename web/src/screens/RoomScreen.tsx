import { useCallback, useMemo, useState } from "react";
import { label, mentionable, status, type JoinLink, type ProposalView } from "@plural/client";
import { Composer } from "../components/Composer";
import { Feed } from "../components/feed/Feed";
import { Inbox } from "../components/inbox/Inbox";
import { inboxItems } from "../components/inbox/items";
import { InviteDialog } from "../components/InviteDialog";
import { Sidebar } from "../components/side/Sidebar";
import { TopBar } from "../components/TopBar";
import { useHotkeys } from "../hooks/useHotkeys";
import { useSession } from "../hooks/useSession";
import { useStickToBottom } from "../hooks/useStickToBottom";
import { useSubmit } from "../hooks/useSubmit";
import { useToast } from "../hooks/useToast";
import { useTyping } from "../hooks/useTyping";
import { activity } from "../lib/activity";
import { copyText } from "../lib/clipboard";
import styles from "./RoomScreen.module.css";

interface RoomScreenProps {
  link: JoinLink;
  name: string;
  onLeave: (reason: string | null) => void;
}
export function RoomScreen({ link, name, onLeave }: RoomScreenProps) {
  const session = useSession(link, name, (reason) => onLeave(reason));
  const { projection, feed, connection, invite, send } = session;
  const state = projection.state;
  const me = projection.me;
  const isHost = me?.role === "host";
  const items = useMemo(() => (isHost ? inboxItems(state) : []), [isHost, state.approvals, state.proposals, state.join_requests]);
  const [editing, setEditing] = useState<ProposalView | null>(null);
  const [panel, setPanel] = useState(false);
  const { toast, flash } = useToast();
  const typing = useTyping(me !== undefined && me.role !== "viewer", send);

  const leave = () => {
    session.close();
    onLeave(null);
  };
  const submit = useSubmit({ session, editing, onEdited: () => setEditing(null), onLeave: leave, flash });
  const focusInput = useCallback(() => document.getElementById("composer")?.focus(), []);
  const canAbort = isHost && state.run !== null && editing === null;

  useHotkeys({ enabled: invite === null, first: items[0], canAbort, send, onEdit: setEditing, onFocusInput: focusInput });

  const writing = feed.items.some((item) => item.kind === "assistant" && item.streaming);
  const current = activity(projection, feed);
  const scroll = useStickToBottom(feed, current?.text);
  const runStatus = writing ? "writing…" : status(projection).replace(/^… /, "");
  const typers = [...projection.typing]
    .filter((id) => id !== projection.meId)
    .map((id) => state.participants[id])
    .filter((person) => person !== undefined)
    .map((person) => label(state, person));
  const placeholder =
    me?.role === "participant" && state.prompt_mode === "review" ? "Propose a prompt, the host approves it" : "Message the agent, / for commands";

  return (
    <div className={styles.room}>
      <TopBar
        room={link.room}
        projection={projection}
        connection={connection}
        panelOpen={panel}
        onCopyRoom={() => void copyText(link.room).then((ok) => ok && flash("room id copied"))}
        onTogglePanel={() => setPanel((open) => !open)}
        onLeave={leave}
      />

      <main className={styles.stage}>
        <div className={styles.scroller} ref={scroll.ref} onScroll={scroll.onScroll}>
          <div className={styles.content}>
            <div className={styles.welcome}>
              You joined room {link.room} as {me ? `${me.name}, ${me.role}` : name}
            </div>
            {!projection.ready ? (
              <div className="muted mono">
                {projection.waiting ? "waiting for the host to let you in…" : connection === "online" ? "loading the session…" : "connecting to the host…"}
              </div>
            ) : null}
            <Feed items={feed.items} meId={projection.meId} activity={current} />
          </div>
        </div>

        <div className={styles.dock}>
          {scroll.behind ? (
            <button className={styles.jump} type="button" onClick={scroll.jump}>
              ↓ latest
            </button>
          ) : null}
          {connection === "offline" ? <div className="banner warn">The connection dropped. Reconnecting…</div> : null}
          <Inbox items={items} state={state} send={send} onEdit={setEditing} />
          <div className={styles.presence}>
            {typers.length > 0 ? (
              <span>
                {typers.length <= 2 ? `${typers.join(" and ")} ${typers.length === 1 ? "is" : "are"} typing…` : `${typers.length} people are typing…`}
              </span>
            ) : null}
            {toast ? <span className={styles.toast}>{toast}</span> : null}
          </div>
          <Composer
            role={me?.role}
            people={mentionable(state, projection.meId)}
            placeholder={placeholder}
            disabled={me?.role === "viewer" ? "Viewers watch the session and can't prompt" : null}
            editing={editing}
            onSubmit={(text) => {
              typing.stop();
              scroll.pin();
              submit(text);
            }}
            onCancelEdit={() => setEditing(null)}
            onEscape={() => canAbort && send({ type: "run.abort" })}
            onActivity={typing.activity}
          />
        </div>
      </main>

      <Sidebar
        projection={projection}
        status={runStatus}
        waiting={items.length}
        open={panel}
        send={send}
        onInvite={(role) => send({ type: "invite.create", role, ttl_s: 3600, reusable: role === "participant" })}
      />

      {invite ? <InviteDialog invite={invite} onClose={session.clearInvite} /> : null}
    </div>
  );
}
