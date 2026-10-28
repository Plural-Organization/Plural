import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { label, mentionable, status, type JoinLink, type ProposalView } from "@plural/client";
import { Board, type Pointer } from "../components/Board";
import { Canvas } from "../components/Canvas";
import { Composer } from "../components/Composer";
import { QuoteButton } from "../components/QuoteButton";
import { SelectionLayer, type Selector } from "../components/SelectionLayer";
import { Feed } from "../components/feed/Feed";
import { Inbox } from "../components/inbox/Inbox";
import { inboxItems } from "../components/inbox/items";
import { InviteDialog } from "../components/InviteDialog";
import { Sidebar } from "../components/side/Sidebar";
import { TopBar } from "../components/TopBar";
import { useAttachments } from "../hooks/useAttachments";
import { useHotkeys } from "../hooks/useHotkeys";
import { useShareSelection } from "../hooks/useShareSelection";
import { useSession } from "../hooks/useSession";
import { useStickToBottom } from "../hooks/useStickToBottom";
import { useSubmit } from "../hooks/useSubmit";
import { useToast } from "../hooks/useToast";
import { useTyping } from "../hooks/useTyping";
import { activity } from "../lib/activity";
import { canvasDocs } from "../lib/canvas";
import { copyText } from "../lib/clipboard";
import { cx } from "../lib/cx";
import styles from "./RoomScreen.module.css";

interface RoomScreenProps {
  link: JoinLink;
  name: string;
  onLeave: (reason: string | null) => void;
}
export function RoomScreen({ link, name, onLeave }: RoomScreenProps) {
  const session = useSession(link, name, (reason) => onLeave(reason));
  const { projection, feed, connection, invite, send, sendPresence } = session;
  const state = projection.state;
  const me = projection.me;
  const isHost = me?.role === "host";
  const items = useMemo(() => (isHost ? inboxItems(state) : []), [isHost, state.approvals, state.proposals, state.join_requests]);
  const [editing, setEditing] = useState<ProposalView | null>(null);
  const [panel, setPanel] = useState(false);
  const { toast, flash } = useToast();
  const docs = useMemo(() => canvasDocs(feed.items), [feed.items]);
  const [canvasId, setCanvasId] = useState<string | null>(null);
  const [quote, setQuote] = useState<{ text: string; key: number } | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const doc = docs.find((item) => item.id === canvasId) ?? null;
  useShareSelection(projection.ready, connection, sendPresence);
  const selectionKey = JSON.stringify([...projection.selections]);
  const selectors: Selector[] = useMemo(
    () =>
      [...projection.selections]
        .filter(([id]) => id !== projection.meId)
        .map(([id, selection]) => ({ id, selection, name: state.participants[id] ? label(state, state.participants[id]!) : "someone" })),
    [selectionKey, state.participants, projection.meId],
  );

  // A document that appears during the session opens for everyone; the ones already in the history wait for a click.
  useEffect(() => {
    if (!projection.ready) {
      return;
    }
    if (seen.current === null) {
      seen.current = new Set(docs.map((item) => item.id));
      return;
    }
    const fresh = docs.filter((item) => !seen.current!.has(item.id));
    fresh.forEach((item) => seen.current!.add(item.id));
    const open = fresh.filter((item) => item.auto).at(-1);
    if (open !== undefined) {
      setCanvasId(open.id);
    }
  }, [docs, projection.ready]);
  const typing = useTyping(me !== undefined && me.role !== "viewer", send);

  const leave = () => {
    session.close();
    onLeave(null);
  };
  const canDraw = me !== undefined && me.role !== "viewer";
  const [boardShown, setBoardShown] = useState(false);
  const showBoard = () => {
    setBoardShown(true);
    setCanvasId(null);
  };
  // Whoever opens the board opens it for the whole room, each time; anyone may still hide it for themselves.
  const lastBoardNotice = feed.items.filter((item) => item.kind === "notice" && item.action === "board").at(-1)?.id ?? null;
  const boardSeen = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (!projection.ready) {
      return;
    }
    if (boardSeen.current === undefined ? state.board.open : lastBoardNotice !== null && lastBoardNotice !== boardSeen.current) {
      showBoard();
    }
    boardSeen.current = lastBoardNotice;
  }, [lastBoardNotice, projection.ready]);
  useEffect(() => {
    if (!state.board.open) {
      setBoardShown(false);
    }
  }, [state.board.open]);
  const draw = () => {
    if (canDraw) {
      send({ type: "board.open", open: true });
    } else if (state.board.open) {
      showBoard();
    } else {
      flash("the board is closed; someone who can prompt opens it");
    }
  };
  const pointerKey = JSON.stringify([...projection.cursors]);
  const pointers: Pointer[] = useMemo(
    () =>
      [...projection.cursors]
        .filter(([id]) => id !== projection.meId)
        .map(([id, cursor]) => ({ id, cursor, name: state.participants[id] ? label(state, state.participants[id]!) : "someone" })),
    [pointerKey, state.participants, projection.meId],
  );

  const files = useAttachments(projection, send, (text) => session.notify("warn", text));
  const submitText = useSubmit({ session, editing, onEdited: () => setEditing(null), onLeave: leave, flash, onDraw: draw });
  const submit = (text: string) => {
    if (files.attachments.length === 0 || editing || text.startsWith("/") || text.startsWith("@")) {
      submitText(text);
      return;
    }
    const pending = files.take();
    void files.ids(pending).then((ids) => {
      if (ids === null) {
        files.restore(pending);
        session.notify("danger", "the files did not reach the host; try sending again");
        return;
      }
      send({ type: "prompt.submit", text: text || "(see the attached files)", delivery: "now", attachments: ids });
    });
  };
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
    <div className={cx(styles.room, (doc || boardShown) && styles.withCanvas)}>
      <TopBar
        room={link.room}
        projection={projection}
        connection={connection}
        panelOpen={panel && doc === null}
        onCopyRoom={() => void copyText(link.room).then((ok) => ok && flash("room id copied"))}
        onTogglePanel={() => {
          setCanvasId(null);
          setBoardShown(false);
          setPanel((open) => !open || doc !== null || boardShown);
        }}
        onLeave={leave}
      />

      <main className={styles.stage}>
        <div className={styles.scroller} ref={scroll.ref} onScroll={scroll.onScroll}>
          <div className={styles.content} data-quotable>
            <SelectionLayer selectors={selectors} version={feed.items} />
            <div className={styles.welcome}>
              You joined room {link.room} as {me ? `${me.name}, ${me.role}` : name}
            </div>
            {!projection.ready ? (
              <div className="muted mono">
                {projection.waiting ? "waiting for the host to let you in…" : connection === "online" ? "loading the session…" : "connecting to the host…"}
              </div>
            ) : null}
            <Feed items={feed.items} meId={projection.meId} activity={current} onOpenBoard={state.board.open ? showBoard : undefined} onOpenDoc={(id) => {
                setBoardShown(false);
                setCanvasId(id);
              }} />
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
            quote={quote}
            attachments={canDraw ? files.attachments : []}
            onAttach={canDraw ? (list) => list.forEach((file) => void files.add(file, file.name || "pasted-image.png")) : undefined}
            onDetach={files.remove}
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

      {boardShown ? (
        <Board
          strokes={state.board.strokes}
          pointers={pointers}
          meId={projection.meId}
          canDraw={canDraw}
          isHost={isHost}
          send={send}
          sendPresence={sendPresence}
          onSendToAgent={(image) => {
            void files.add(image, `board-${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.png`);
            flash("the board is attached; add a note and send");
            document.getElementById("composer")?.focus();
          }}
          onClose={() => setBoardShown(false)}
        />
      ) : doc ? (
        <Canvas doc={doc} docs={docs} selectors={selectors} onPick={setCanvasId} onClose={() => setCanvasId(null)} />
      ) : (
        <Sidebar
          projection={projection}
          status={runStatus}
          waiting={items.length}
          open={panel}
          send={send}
          onInvite={(role) => send({ type: "invite.create", role, ttl_s: 3600, reusable: role === "participant" })}
        />
      )}

      <QuoteButton enabled={me !== undefined && me.role !== "viewer"} onQuote={(text) => setQuote((current) => ({ text, key: (current?.key ?? 0) + 1 }))} />
      {invite ? <InviteDialog invite={invite} onClose={session.clearInvite} /> : null}
    </div>
  );
}
