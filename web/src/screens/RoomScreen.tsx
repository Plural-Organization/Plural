import { Alert, Button, Spinner } from "@heroui/react";
import { ArrowDown } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { label, mentionable, status, type JoinLink, type ProposalView } from "@plural/client";
import { Board, type Pointer } from "../components/Board";
import { Canvas } from "../components/Canvas";
import { Composer } from "../components/Composer";
import { QuoteButton } from "../components/QuoteButton";
import { SelectionLayer, type Selector } from "../components/SelectionLayer";
import { SitePreview } from "../components/SitePreview";
import { Feed } from "../components/feed/Feed";
import { Inbox } from "../components/inbox/Inbox";
import { askItems, inboxItems } from "../components/inbox/items";
import { InviteDialog } from "../components/InviteDialog";
import { TraceView } from "../components/TraceView";
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
import type { Team } from "../lib/team";
import { activity } from "../lib/activity";
import { canvasDocs } from "../lib/canvas";
import { siteFiles } from "../lib/site";
import { copyText } from "../lib/clipboard";
import { upload } from "../lib/upload";
import { cx } from "../lib/cx";
import { pluginHints, skillHints } from "../lib/commands";
import styles from "./RoomScreen.module.css";
import { isNarrow, SIDE_WIDTH } from "../lib/panels";
import { ResizeHandle } from "../components/ResizeHandle";

interface RoomScreenProps {
  link: JoinLink;
  name: string;
  // The team this room was opened through, if it was.
  member: Team | null;
  // Shown now; the others stay connected in the background.
  active: boolean;
  // Why another space closed, said here when this one takes its place.
  notice?: string | null;
  // Brings back the list of sessions on a narrow screen.
  railTucked: boolean;
  // The room panel, the same in every open room.
  side: { tucked: boolean; width: number; setTucked: (tucked: boolean) => void; setWidth: (width: number) => void };
  onToggleRail: () => void;
  // Says whose session this is, once the room knows.
  onHost: (name: string) => void;
  onLeave: (reason: string | null) => void;
}
export function RoomScreen({ link, name, member, active, notice = null, railTucked, side, onToggleRail, onHost, onLeave }: RoomScreenProps) {
  // The session keeps the callback it started with, so it calls the latest one through a ref.
  const leaving = useRef(onLeave);
  leaving.current = onLeave;
  const session = useSession(link, name, (reason) => leaving.current(reason), member);
  const { projection, feed, connection, invite, send, sendPresence } = session;
  const state = projection.state;
  const me = projection.me;
  const pluginCommands = useMemo(() => [...pluginHints(state.commands), ...skillHints(state.skills)], [state.commands, state.skills]);
  const isHost = me?.role === "host";
  const hostName = Object.values(state.participants).find((person) => person.role === "host")?.name;
  useEffect(() => {
    if (hostName !== undefined) {
      onHost(hostName);
    }
  }, [hostName]);
  const items = useMemo(
    () => [...askItems(session.asks), ...(isHost ? inboxItems(state) : [])],
    [session.asks, isHost, state.approvals, state.proposals, state.join_requests],
  );
  const [editing, setEditing] = useState<ProposalView | null>(null);
  const [panel, setPanel] = useState(false);
  const { tucked: sideTucked, width: sideWidth, setTucked: setSideTucked, setWidth: setSideWidth } = side;
  const { toast, flash } = useToast();
  useEffect(() => {
    if (notice) {
      flash(notice);
    }
  }, [notice]);
  const site = useMemo(() => siteFiles(feed.items), [feed.items]);
  const docs = useMemo(() => {
    const documents = canvasDocs(feed.items, site);
    if (state.preview) documents.push({ id: `dev:${state.preview.id}`, title: state.preview.title, kind: "site", lang: "html", text: "/", live: false, auto: true, previewId: state.preview.id });
    return documents;
  }, [feed.items, site, state.preview]);
  const [canvasId, setCanvasId] = useState<string | null>(null);
  const [quote, setQuote] = useState<{ text: string; key: number } | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const doc = docs.find((item) => item.id === canvasId) ?? null;
  useShareSelection(projection.ready && active, connection, sendPresence);
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
  // The board or the canvas may take the whole screen; the toggle brings it back to half.
  const [wide, setWide] = useState(false);
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
  const everyPointer: Pointer[] = useMemo(
    () =>
      [...projection.cursors]
        .filter(([id]) => id !== projection.meId)
        .map(([id, cursor]) => ({ id, cursor, name: state.participants[id] ? label(state, state.participants[id]!) : "someone" })),
    [pointerKey, state.participants, projection.meId],
  );
  // A pointer is on the board or on the site preview, and shows only there.
  const pointers = useMemo(() => everyPointer.filter((pointer) => pointer.cursor.surface !== "preview"), [everyPointer]);
  const previewPointers = useMemo(() => everyPointer.filter((pointer) => pointer.cursor.surface === "preview"), [everyPointer]);

  const files = useAttachments(projection, send, (text) => session.notify("warn", text));
  const submitText = useSubmit({ session, editing, onEdited: () => setEditing(null), onLeave: leave, flash, onDraw: draw });
  // Prompts leave in the order they were written, even when one waits for its files to upload.
  const outbox = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);
  const submit = (text: string) => {
    const withFiles = files.attachments.length > 0;
    if (withFiles && (editing !== null || text.startsWith("/") || text.startsWith("@"))) {
      if (text === "") {
        flash("write something to go with the files");
        return;
      }
      submitText(text);
      flash("the files stay for your next prompt");
      return;
    }
    if (withFiles && !files.ready) {
      flash("the files are still loading");
      return;
    }
    if (!withFiles && waiting.current === 0) {
      submitText(text);
      return;
    }
    const pending = withFiles ? files.take() : [];
    waiting.current += 1;
    outbox.current = outbox.current.then(async () => {
      try {
        if (pending.length === 0) {
          submitText(text);
          return;
        }
        const ids = await files.ids(pending);
        if (ids === null) {
          files.restore(pending);
          session.notify("danger", "the files did not reach the host; try sending again");
          return;
        }
        files.release(pending);
        send({ type: "prompt.submit", text: text || "(see the attached files)", delivery: "now", attachments: ids });
      } finally {
        waiting.current -= 1;
      }
    });
  };
  // Each open space has its own composer, so the lookup stays inside this room.
  const root = useRef<HTMLDivElement>(null);
  const focusInput = useCallback(() => root.current?.querySelector<HTMLElement>("#composer")?.focus(), []);
  const canAbort = isHost && state.run !== null && editing === null;

  const traceOpen = session.trace !== null;
  const toggleTrace = () => (traceOpen ? session.closeTrace() : session.openTrace());
  // While the trace is open its own keys rule: esc closes it instead of stopping the run.
  useHotkeys({ enabled: invite === null && active && !traceOpen, first: items[0], canAbort, send, onEdit: setEditing, onFocusInput: focusInput, onTrace: session.openTrace });
  useEffect(() => {
    if (!traceOpen) return;
    // t closes the trace too, unless someone is typing.
    const onKey = (event: KeyboardEvent) => {
      const typing = event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]") !== null;
      if (event.key === "t" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        session.closeTrace();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [traceOpen]);

  const writing = feed.items.some((item) => item.kind === "assistant" && item.streaming);
  const current = activity(projection, feed);
  const scroll = useStickToBottom(feed, current?.text, active);
  const runStatus = writing ? "writing…" : status(projection).replace(/^… /, "");
  const typers = [...projection.typing]
    .filter((id) => id !== projection.meId)
    .map((id) => state.participants[id])
    .filter((person) => person !== undefined)
    .map((person) => label(state, person));
  const placeholder =
    me?.role === "viewer"
      ? me.id in state.access_requests
        ? "Waiting for the host. Type / for commands"
        : "Type / for commands"
      : me?.role === "participant" && state.prompt_mode === "review"
        ? "Propose a prompt, the host approves it"
        : "Message the agent, / for commands";

  return (
    <div ref={root} className={cx(styles.room, (doc || boardShown) && styles.withCanvas, !doc && !boardShown && sideTucked && styles.tucked)} style={{ "--side": `${sideWidth}px` } as CSSProperties}>
      <TopBar
        room={link.room}
        projection={projection}
        connection={connection}
        panelOpen={!sideTucked || doc !== null || boardShown}
        panelShown={panel && doc === null}
        railOpen={!railTucked}
        onCopyRoom={() => void copyText(link.room).then((ok) => ok && flash("room id copied"))}
        onTogglePanel={() => {
          setCanvasId(null);
          setBoardShown(false);
          if (isNarrow()) setPanel((open) => !open || doc !== null || boardShown);
          // On a wide screen an open canvas gives way to the panel; otherwise the panel comes and goes.
          else setSideTucked(doc === null && !boardShown && !sideTucked);
        }}
        onLeave={leave}
        onToggleRail={onToggleRail}
        traceOpen={traceOpen}
        onToggleTrace={toggleTrace}
      />

      <main className={styles.stage}>
        <div className={styles.scroller} ref={scroll.ref} onScroll={scroll.onScroll}>
          <div className={styles.content} data-quotable>
            <SelectionLayer selectors={selectors} version={feed.items} />
            <div className={styles.welcome}>
              You joined as {me ? `${me.name}, ${me.role}` : name}
            </div>
            {!projection.ready ? (
              <div className="flex items-center justify-center gap-2.5 py-10 text-sm text-muted">
                <Spinner size="sm" color="current" />
                {projection.waiting ? "waiting for the host to let you in…" : connection === "online" ? "loading the session…" : "connecting to the host…"}
              </div>
            ) : null}
            {projection.ready && !feed.items.some((item) => item.kind === "user" || item.kind === "chat" || item.kind === "assistant") ? (
              <div className={styles.empty}>
                <h2 className="font-display">
                  One agent, the whole team.
                  <br />
                  <span className="tone-2">Ask it anything.</span>
                </h2>
                <p>Everyone here sees the same conversation. Type <kbd>/</kbd> for commands or <kbd>@</kbd> to tag someone.</p>
              </div>
            ) : null}
            <Feed items={feed.items} people={mentionable(state, null)} meId={projection.meId} activity={current} onOpenBoard={state.board.open ? showBoard : undefined} onOpenDoc={(id) => {
                setBoardShown(false);
                setCanvasId(id);
              }} />
          </div>
        </div>

        <div className={styles.dock}>
          {scroll.behind ? (
            <Button size="sm" variant="tertiary" className={styles.jump} onPress={scroll.jump}>
              <ArrowDown size={14} />
              Latest
            </Button>
          ) : null}
          {connection === "offline" ? (
            <Alert status="warning">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>The connection dropped. Reconnecting…</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
          <Inbox items={items} state={state} send={send} onEdit={setEditing} answer={session.answer} />
          <div className={styles.presence}>
            {typers.length > 0 ? (
              <span>
                {typers.length <= 2 ? `${typers.join(" and ")} ${typers.length === 1 ? "is" : "are"} typing…` : `${typers.length} people are typing…`}
              </span>
            ) : null}
            {toast ? <span className={styles.toast}>{toast}</span> : null}
          </div>
          {me?.role === "viewer" ? (
            <div className={styles.watching}>
              <span>You are watching this session.</span>
              <Button size="sm" variant="tertiary" isDisabled={me.id in state.access_requests} onPress={() => submit("/access")}>
                {me.id in state.access_requests ? "Waiting for the host" : "Ask to write"}
              </Button>
            </div>
          ) : null}
          <Composer
            role={me?.role}
            people={mentionable(state, projection.meId)}
            commands={pluginCommands}
            placeholder={placeholder}
            disabled={null}
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

      {boardShown && active ? (
        <Board
          strokes={state.board.strokes}
          pointers={pointers}
          meId={projection.meId}
          canDraw={canDraw}
          isHost={isHost}
          pictures={session.pictures}
          fetchPicture={session.fetchPicture}
          uploadPicture={(file, name) => upload(file, name, projection, send)}
          onNotice={(text) => session.notify("warn", text)}
          send={send}
          sendPresence={sendPresence}
          onSendToAgent={(image) => {
            void files.add(image, `board-${new Date().toISOString().slice(11, 19).replace(/:/g, "")}.png`);
            flash("the board is attached; add a note and send");
            focusInput();
          }}
          onClose={() => setBoardShown(false)}
          full={wide}
          onToggleFull={() => setWide((value) => !value)}
        />
      ) : doc ? (
        <Canvas
          doc={doc}
          docs={docs}
          selectors={selectors}
          full={wide}
          onToggleFull={() => setWide((value) => !value)}
          onPick={setCanvasId}
          onClose={() => setCanvasId(null)}
          site={(page) => (
            <SitePreview
              key={page.id}
              entry={page.text}
              remote={page.previewId ? { id: page.previewId, open: session.openPreview } : undefined}
              site={site}
              pointers={previewPointers}
              echo={projection.meId === null ? undefined : projection.cursors.get(projection.meId)}
              canPick={canDraw}
              sendPresence={sendPresence}
              onAsk={(text) => {
                scroll.pin();
                submit(text);
              }}
              onNotice={flash}
            />
          )}
        />
      ) : (
        <Sidebar
          projection={projection}
          status={runStatus}
          waiting={items.length}
          open={panel}
          tucked={sideTucked}
          onHide={() => (isNarrow() ? setPanel(false) : setSideTucked(true))}
          send={send}
          onInvite={(role) => send({ type: "invite.create", role, ttl_s: 3600, reusable: role === "participant" })}
        />
      )}
      {!doc && !boardShown && !sideTucked ? (
        <ResizeHandle label="Width of the room panel" width={sideWidth} bounds={SIDE_WIDTH} direction={-1} onResize={setSideWidth} style={{ right: sideWidth, top: 56 }} />
      ) : null}

      <QuoteButton enabled={active && me !== undefined && me.role !== "viewer"} onQuote={(text) => setQuote((current) => ({ text, key: (current?.key ?? 0) + 1 }))} />
      {invite && active ? <InviteDialog invite={invite} onClose={session.clearInvite} /> : null}
      {session.trace && active ? <TraceView trace={session.trace} projection={projection} send={send} onClose={session.closeTrace} /> : null}
    </div>
  );
}
